"""Storage-only migration helpers. Default check is read-only; never delete data."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing
import uuid


class Blocked(RuntimeError):
    pass


def safe(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise Blocked('Unsafe manifest path')
    candidate = root / relative
    current = candidate
    while current != root:
        if current.is_symlink():
            raise Blocked(f'Nested symlink needs manual review: {current}')
        current = current.parent
    if not candidate.resolve().is_relative_to(root):
        raise Blocked('Path escapes resolved data root')
    return candidate


def sha(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise Blocked(f'Source changed during hashing: {path}')
    return digest.hexdigest()


def inspect(path, operation):
    if not path.is_file():
        raise Blocked(f'Source missing: {path}')
    for suffix in ('-wal', '-journal'):
        sibling = path.with_name(path.name + suffix)
        if sibling.exists() and sibling.stat().st_size:
            raise Blocked(f'Writer/journal requires stable snapshot: {sibling}')
    if path.stat().st_size != operation['expectedBytes']:
        raise Blocked(f'Audit size changed; refresh manifest: {path}')
    fingerprint = sha(path)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)) as db:
        integrity = [row[0] for row in db.execute('PRAGMA integrity_check')]
        if integrity != ['ok']:
            raise Blocked(f'SQLite integrity failed: {path}')
        metadata = dict(db.execute('SELECT name,value FROM metadata'))
        layers = json.loads(metadata.get('json', '{}')).get('vector_layers', [])
        if not layers and metadata.get('vector_layers'):
            layers = json.loads(metadata['vector_layers'])
        if {layer['id'] for layer in layers} != set(operation['expectedSourceLayers']):
            raise Blocked(f'Source-layer inventory changed: {path}')
        if not db.execute('SELECT 1 FROM tiles WHERE length(tile_data)>0 LIMIT 1').fetchone():
            raise Blocked(f'No nonempty tiles: {path}')
    if sha(path) != fingerprint:
        raise Blocked(f'Source changed during integrity inspection: {path}')
    return fingerprint


def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def rename_no_replace(source, destination):
    # Kernel-enforced no-clobber, even if another process races destination checks.
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, 'renameat2', None)
    if function is None:
        raise Blocked('Linux renameat2 required; no unsafe rename fallback')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if function(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
    syncdir(source.parent)
    syncdir(destination.parent)


def preflight(manifest, root):
    root = Path(root).resolve(strict=True)
    fingerprints, destinations = {}, set()
    operations = manifest['operations']
    if not operations:
        raise Blocked('No operations')
    for operation in operations:
        if operation['kind'] != 'link':
            raise Blocked('Unsupported operation')
        source = safe(root, operation['source'])
        destination = safe(root, operation['destination'])
        if destination == source or destination in destinations:
            raise Blocked('Invalid operation order or duplicate destination')
        if destination.exists():
            raise Blocked(f'Destination occupied; no overwrite allowed: {destination}')
        ancestor = destination.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        if source.stat().st_dev != ancestor.stat().st_dev:
            raise Blocked('Cross-filesystem migration unsupported; prepare verified copy plan separately')
        fingerprints[operation['id']] = inspect(source, operation)
        destinations.add(destination)
    if shutil.disk_usage(root).free < max(16*1024*1024, len(operations)*65536):
        raise Blocked('Insufficient metadata/free-space reserve for hard links and receipts')
    return root, fingerprints


def save_receipt(path, receipt, initial=False):
    encoded = json.dumps(receipt, indent=2).encode()+b'\n'
    if initial:
        with path.open('xb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        with temporary.open('xb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)  # Only this transaction's receipt; never archive data.
    syncdir(path.parent)


def apply(manifest, root, receipt_path, approved=False, dependencies_reviewed=False):
    if not approved or not dependencies_reviewed:
        raise Blocked('Explicit deployment approval and completed dependency review are required')
    receipt_path = Path(receipt_path).resolve()
    if receipt_path.exists():
        raise Blocked('Receipt already exists; cannot repeat or overwrite a transaction')
    root, fingerprints = preflight(manifest, root)
    if receipt_path.is_relative_to(root):
        raise Blocked('Receipt must be outside production data root')
    if not receipt_path.parent.is_dir():
        raise Blocked('Create a separate receipt directory before execution')
    receipt = {'version': 1, 'transaction': uuid.uuid4().hex, 'root': str(root),
               'status': 'applying', 'operations': [], 'backendModified': False}
    save_receipt(receipt_path, receipt, initial=True)
    for operation in manifest['operations']:
        source, destination = safe(root, operation['source']), safe(root, operation['destination'])
        if sha(source) != fingerprints[operation['id']]:
            raise Blocked('Source changed since preflight; stop and retain all data')
        if destination.exists():
            raise Blocked('Destination became occupied; stop without overwrite')
        destination.parent.mkdir(parents=True, exist_ok=True)
        entry = {**operation, 'sha256': fingerprints[operation['id']], 'status': 'pending'}
        receipt['operations'].append(entry)
        save_receipt(receipt_path, receipt)
        os.link(source, destination, follow_symlinks=False)
        syncdir(destination.parent)
        if sha(destination) != entry['sha256']:
            raise Blocked('Post-operation SHA256 mismatch; retain all paths for review')
        entry['status'] = 'done'
        save_receipt(receipt_path, receipt)
    receipt['status'] = 'complete'
    save_receipt(receipt_path, receipt)
    return receipt


def rollback(receipt_path, execute=False, approved=False, dependencies_reviewed=False):
    receipt_path = Path(receipt_path).resolve(strict=True)
    receipt = json.loads(receipt_path.read_text())
    root = Path(receipt['root']).resolve(strict=True)
    if execute and (not approved or not dependencies_reviewed):
        raise Blocked('Rollback needs explicit approval and dependency review')
    if receipt.get('status') == 'rolled-back':
        raise Blocked('Transaction already rolled back; no repeated filesystem operations')
    transaction = receipt['transaction']
    if not transaction.isalnum():
        raise Blocked('Invalid transaction identifier')
    reverse, vacated = [], set()
    for entry in reversed(receipt['operations']):
        if entry['status'] != 'done':
            raise Blocked('Interrupted pending operation requires manual reconciliation; no automatic guess')
        current = safe(root, entry['destination'])
        if entry['kind'] != 'link':
            raise Blocked('Unsupported receipt operation; do not move original source archives')
        original = safe(root, entry['source'])
        if not original.is_file() or sha(original) != entry['sha256']:
            raise Blocked('Original archive changed or disappeared; manual review required')
        # Retain every generated alias: rollback never unlinks or deletes a file.
        relative = Path(entry['destination'])
        destination = safe(root, f'{relative.parts[0]}/migration-rollback/tiles/{transaction}-{relative.name}')
        if not current.is_file() or sha(current) != entry['sha256']:
            raise Blocked('Rollback content changed or missing; retain all data for review')
        if destination.exists() and destination not in vacated:
            raise Blocked(f'Rollback target occupied: {destination}')
        vacated.add(current)
        reverse.append((entry, current, destination))
    if execute:
        for entry, source, destination in reverse:
            destination.parent.mkdir(parents=True, exist_ok=True)
            rename_no_replace(source, destination)
            if sha(destination) != entry['sha256']:
                raise Blocked('Rollback SHA256 mismatch; retain data for review')
            entry['rollbackRetainedAt'] = str(destination)
            save_receipt(receipt_path, receipt)
        receipt['status'] = 'rolled-back'
        save_receipt(receipt_path, receipt)
    return {'status': 'rolled-back' if execute else 'rollback-check-passed',
            'operations': len(reverse), 'filesDeleted': 0, 'backendModified': False}
