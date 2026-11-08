#!/usr/bin/env python3
"""Build only a caller-prepared Android snapshot; no mounting or data generation.
Manifest: JSON {schema:1,version_code:string,version_name:string,files:{path:sha256}}.
The supplied manifest detects changes; it does not establish origin or rights.
This is not a sandbox. The caller must review and trust ALL source, generated
scripts, data and toolchains. Extension checks cannot detect all secrets.
Races, malicious remounts, external system-cache writes and malicious code
(including device operations) are not prevented.
"""
import argparse, hashlib, json, os, plistlib, re, shutil, stat, subprocess, sys, tempfile, zipfile
from pathlib import Path, PurePosixPath

# BEGIN TA_RANK_PINNED_INPUT_HELPERS
TA_RANK_HEADER_SHA256 = '15a12c68b1bd40f3e8cdeaeccbf4d8dc0cd2cda4f7f9655c4ea73f59c0d68457'
def ta_rank_stable_file(path, limit):
    before=path.lstat()
    def identity(s):
        return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>limit:
        raise ValueError('TA input must be a bounded regular single-link file: '+str(path))
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        opened=os.fstat(f.fileno())
        if identity(opened)!=identity(before):raise ValueError('TA input changed before read')
        data=f.read(limit+1)
        if len(data)>limit or len(data)!=opened.st_size or identity(os.fstat(f.fileno()))!=identity(opened):
            raise ValueError('TA input changed during read')
    if identity(path.lstat())!=identity(opened):raise ValueError('TA input changed after read')
    return data,{'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'stat':list(identity(opened))}
def ta_rank_read(directory, source_root):
    if not directory:raise ValueError('TA_RANK_PRIVATE_INCLUDE is required')
    path=Path(directory)
    if not path.is_absolute() or directory!=os.path.normpath(directory) or path.resolve(strict=True)!=path:
        raise ValueError('TA_RANK_PRIVATE_INCLUDE must be an absolute canonical non-symlink directory')
    if not stat.S_ISDIR(path.lstat().st_mode) or path.is_relative_to(Path(source_root).resolve(strict=True)):
        raise ValueError('Private TA generated input must be a directory outside the source snapshot')
    if os.path.lexists(Path(source_root)/'src/ta_rank_assets_private.h'):
        raise ValueError('Source-local TA header would shadow the verified private include')
    header,header_record=ta_rank_stable_file(path/'ta_rank_assets_private.h',8*1024*1024)
    if header_record['sha256']!=TA_RANK_HEADER_SHA256:raise ValueError('TA header differs from fixed reviewed SHA-256')
    proof=None;proof_record=None;proof_path=path/'ta-rank-assets-proof.json'
    if os.path.lexists(proof_path):
        proof,proof_record=ta_rank_stable_file(proof_path,1024*1024)
        if json.loads(proof)['header']['sha256']!=TA_RANK_HEADER_SHA256:
            raise ValueError('TA provenance proof/header digest mismatch')
    # Proof metadata is a retained readset, never authority to change the fixed pin.
    return header,proof,{'schema':'ta-rank-private-build-readset-v1','expected_header_sha256':TA_RANK_HEADER_SHA256,'header':header_record,'proof':proof_record}
def ta_rank_publish(inputs, directory):
    header,proof,readset=inputs;directory=Path(directory)
    directory.mkdir(mode=0o700)
    rows=[('ta_rank_assets_private.h',header),('readset.json',(json.dumps(readset,sort_keys=True,indent=2)+'\n').encode())]
    if proof is not None:rows.append(('ta-rank-assets-proof.json',proof))
    for name,data in rows:
        fd=os.open(str(directory/name),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    fd=os.open(str(directory),os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return directory
# END TA_RANK_PINNED_INPUT_HELPERS

# BEGIN VEHICLE_RESTORE_PINNED_INPUT_HELPERS
VEHICLE_RESTORE_HEADERS = {
    'body_color_assets_private.h': '9d400fbcbb480579afd1dcf759a4ffae07cf1a9adbedfa78a5c1727e504ecb87',
    'player_paint_profile_private.h': '88631bfff65ae050881d85d71b73783b1eed11f5972a53dbdbd94a8d00c59075',
    'player_paint_model_profile_private.h': '92093cfb799b19f73877a9590d8f3bf6154928e39c9cdc77a2074deee5ae8957',
}
VEHICLE_RESTORE_MAX_HEADER_BYTES = 8 * 1024 * 1024

def vehicle_restore_identity(s):
    return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_uid,s.st_gid,
            s.st_size,s.st_mtime_ns,s.st_ctime_ns)

def vehicle_restore_stable_file(directory_fd, directory, name):
    before=os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or
            not 0<before.st_size<=VEHICLE_RESTORE_MAX_HEADER_BYTES):
        raise ValueError('Vehicle input must be a bounded regular single-link file: '+str(directory/name))
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory_fd)
    with os.fdopen(fd,'rb') as f:
        opened=os.fstat(f.fileno())
        if vehicle_restore_identity(opened)!=vehicle_restore_identity(before):
            raise ValueError('Vehicle input changed before read')
        data=f.read(VEHICLE_RESTORE_MAX_HEADER_BYTES+1)
        if (len(data)!=opened.st_size or len(data)>VEHICLE_RESTORE_MAX_HEADER_BYTES or
                vehicle_restore_identity(os.fstat(f.fileno()))!=vehicle_restore_identity(opened)):
            raise ValueError('Vehicle input changed during read')
    after=os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
    if vehicle_restore_identity(after)!=vehicle_restore_identity(opened):
        raise ValueError('Vehicle input changed after read')
    digest=hashlib.sha256(data).hexdigest()
    if digest!=VEHICLE_RESTORE_HEADERS[name]:
        raise ValueError('Vehicle header differs from fixed reviewed SHA-256: '+name)
    return data,{'path':str(directory/name),'sha256':digest,'bytes':len(data),
                 'stat':list(vehicle_restore_identity(opened))}

def vehicle_restore_read(directory, source_root):
    if not isinstance(directory,str) or not directory:
        raise ValueError('VEHICLE_RESTORE_PRIVATE_INCLUDE is required')
    path=Path(directory);source=Path(source_root).resolve(strict=True)
    if (not path.is_absolute() or directory!=os.path.normpath(directory) or
            path.resolve(strict=True)!=path):
        raise ValueError('VEHICLE_RESTORE_PRIVATE_INCLUDE must be an absolute canonical non-symlink directory')
    before=path.lstat()
    if not stat.S_ISDIR(before.st_mode) or path.is_relative_to(source):
        raise ValueError('Private vehicle generated input must be a directory outside the source snapshot')
    for name in VEHICLE_RESTORE_HEADERS:
        for parent in (source,source/'src'):
            if os.path.lexists(parent/name):
                raise ValueError('Source-local vehicle header would shadow the verified private include: '+name)
    # Anchoring reads to the verified directory prevents following a substituted
    # parent path. The complete pathname and directory stat are rechecked too.
    fd=os.open(str(path),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        if vehicle_restore_identity(os.fstat(fd))!=vehicle_restore_identity(before):
            raise ValueError('Vehicle include directory changed before open')
        headers={};records={}
        for name in VEHICLE_RESTORE_HEADERS:
            headers[name],records[name]=vehicle_restore_stable_file(fd,path,name)
        if (vehicle_restore_identity(os.fstat(fd))!=vehicle_restore_identity(before) or
                vehicle_restore_identity(path.lstat())!=vehicle_restore_identity(before) or
                path.resolve(strict=True)!=path):
            raise ValueError('Vehicle include directory changed during read')
    finally:os.close(fd)
    return headers,{'schema':'vehicle-restore-private-build-readset-v1',
                    'expected_header_sha256':dict(VEHICLE_RESTORE_HEADERS),
                    'headers':records,'source_root':str(source),
                    'directory_stat':list(vehicle_restore_identity(before))}

def vehicle_restore_publish(inputs, directory):
    headers,readset=inputs
    if (set(headers)!=set(VEHICLE_RESTORE_HEADERS) or
            readset.get('schema')!='vehicle-restore-private-build-readset-v1' or
            readset.get('expected_header_sha256')!=VEHICLE_RESTORE_HEADERS or
            set(readset.get('headers',{}))!=set(VEHICLE_RESTORE_HEADERS)):
        raise ValueError('Invalid vehicle private build capability')
    for name,digest in VEHICLE_RESTORE_HEADERS.items():
        data=headers[name];record=readset['headers'][name]
        if (not isinstance(data,bytes) or hashlib.sha256(data).hexdigest()!=digest or
                record.get('sha256')!=digest or record.get('bytes')!=len(data)):
            raise ValueError('Vehicle private capability changed before publication')
    directory=Path(directory);directory.mkdir(mode=0o700)
    fd=os.open(str(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        # Only the newly created directory/files are normalized, never inputs.
        os.fchmod(fd,0o700)
        rows=[*headers.items(),('readset.json',(json.dumps(readset,sort_keys=True,indent=2)+'\n').encode())]
        for name,data in rows:
            child=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=fd)
            with os.fdopen(child,'wb') as f:
                os.fchmod(f.fileno(),0o600);f.write(data);f.flush();os.fsync(f.fileno())
        os.fsync(fd)
    finally:os.close(fd)
    return directory
# END VEHICLE_RESTORE_PINNED_INPUT_HELPERS

class Refusal(Exception): pass

def need(ok, msg):
    if not ok: raise Refusal(msg)

def canonical(s):
    p = Path(s)
    need(p.is_absolute() and str(p) == os.path.normpath(str(p)), 'path not absolute and normalized')
    need(str(p.resolve(strict=True)) == str(p), 'path not canonical')
    return p

def system_plist(*command):
    return plistlib.loads(subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout)

def mount_of(path):
    while path.parent != path and path.stat().st_dev == path.parent.stat().st_dev: path = path.parent
    return path

def validate_volume(root, bundle, space):
    need(not any(c.isspace() for c in str(root)), 'root contains whitespace')
    need(root.is_dir() and bundle.is_dir() and bundle.name.endswith('.sparsebundle'), 'invalid root or bundle')
    info = system_plist('/usr/sbin/diskutil', 'info', '-plist', str(root))
    need(info.get('MountPoint') == str(root) and info.get('FilesystemType') == 'apfs' and info.get('BusProtocol') == 'Disk Image' and info.get('WritableVolume') is True and info.get('WritableMedia') is True, 'invalid APFS image mount')
    stores = info.get('APFSPhysicalStores', [])
    need(len(stores) == 1 and stores[0].get('APFSPhysicalStore'), 'APFS store not uniquely established')
    images = system_plist('/usr/bin/hdiutil', 'info', '-plist').get('images', [])
    images = [i for i in images if i.get('image-path') == str(bundle)]
    need(len(images) == 1, 'image attachment is not unique')
    image = images[0]; entities = image.get('system-entities', [])
    need(image.get('image-type') == 'sparse bundle disk image' and image.get('writeable') is True, 'image not writable')
    need(any(e.get('dev-entry') == '/dev/' + stores[0]['APFSPhysicalStore'] for e in entities) and any(e.get('dev-entry') == '/dev/' + info.get('DeviceIdentifier', '') and e.get('mount-point') == str(root) for e in entities), 'image and volume device mismatch')
    hostmount = mount_of(bundle)
    host = system_plist('/usr/sbin/diskutil', 'info', '-plist', str(hostmount))
    need(host.get('MountPoint') == str(hostmount) and host.get('Internal') is False and host.get('WritableVolume') is True and host.get('WritableMedia') is True and host.get('BusProtocol') not in (None, '', 'Disk Image', 'Virtual Interface') and host.get('ParentWholeDisk'), 'backing volume not proven external writable physical')
    disk = system_plist('/usr/sbin/diskutil', 'info', '-plist', host['ParentWholeDisk'])
    need(disk.get('WholeDisk') is True and disk.get('VirtualOrPhysical') == 'Physical' and disk.get('Internal') is False and disk.get('WritableMedia') is True and disk.get('BusProtocol') not in (None, '', 'Disk Image', 'Virtual Interface'), 'backing whole disk not proven external physical writable')
    need(info.get('APFSContainerFree', 0) >= space, 'insufficient APFS container space')
    for p in (root, hostmount):
        v = os.statvfs(p)
        need(v.f_bavail * v.f_frsize >= space, 'insufficient image or host free space')

# Changes to these pins require human source review, not caller-supplied approval.
REVIEWED = {'build_android.sh':'59dab64fb82d33d922e201fc07d01258775abf64547beb1c8675eb6deb404272', 'tools/recomp/guard_sections.py':'61637755f4fa2f288216f2641c67de20b0042b90bd9068d9e0a468acfa220373', 'tools/vkglsl.py':'874aabde05d8886af5606a52434c5cf63304bcb8853c8408ce4a0124fd8dcf7c'}
SECRET = {'.jks','.keystore','.p12','.pfx','.pem','.key','.p8','.p7b','.p7c','.asc','.mobileprovision'}

def scan(root):
    out = {}; base = root.lstat()
    need(stat.S_ISDIR(base.st_mode), 'snapshot is not directory')
    def visit(d, prefix=''):
        with os.scandir(d) as entries:
            for e in entries:
                rel = prefix + e.name; st = e.stat(follow_symlinks=False)
                need(st.st_dev == base.st_dev, 'snapshot crosses filesystem boundary')
                if stat.S_ISDIR(st.st_mode): visit(e.path, rel + '/')
                else:
                    need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, 'symlink, hard link or special file')
                    need(Path(e.name).suffix.lower() not in SECRET, 'secret extension in snapshot')
                    out[rel] = (e.path, st)
    visit(root)
    return out

def digest(path, before):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as f:
        s = os.fstat(f.fileno())
        need(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns) == (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns), 'input changed during read')
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(1048576), b''): h.update(chunk)
        t = os.fstat(f.fileno())
        need((t.st_size,t.st_mtime_ns,t.st_nlink) == (s.st_size,s.st_mtime_ns,1), 'input changed during read')
        return h.hexdigest()

def inventory(root):
    return {name: digest(path, st) for name,(path,st) in scan(root).items()}

def manifest(path, code, name):
    def unique(pairs):
        d = {}
        for k,v in pairs:
            need(k not in d, 'duplicate manifest key'); d[k] = v
        return d
    obj = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
    need(isinstance(obj,dict) and set(obj) == {'schema','version_code','version_name','files'} and type(obj['schema']) is int and obj['schema'] == 1, 'invalid manifest schema')
    need(obj['version_code'] == code and obj['version_name'] == name, 'manifest version conflict')
    files = obj['files']; need(isinstance(files,dict) and 'build_android.sh' in files, 'missing build script')
    for k,v in files.items():
        need(isinstance(k,str) and k and str(PurePosixPath(k)) == k and not k.startswith('/') and all(x not in ('.','..','') for x in k.split('/')) and '\\' not in k and '\x00' not in k, 'invalid manifest path')
        need(Path(k).suffix.lower() not in SECRET and isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v), 'invalid manifest hash or secret extension')
    return files

def verify(root, files):
    actual = inventory(root)
    need(actual == files, 'manifest files or SHA-256 do not match snapshot')

ASSETS = {'GAME_DATA_BASELINES_ZIP':'assets/data-baselines.zip','GAME_DATA_ZIP':'assets/re3dxplus-data.zip','CARD_RESOURCES':'assets/card-resources-v1.zip','STORY_CUTIN_BIN':'assets/story-cutin.bin','CARD_PAGES_BIN':'assets/card-pages.bin','BACKFIRE_WPK':'assets/backfire.wpk','BACKFIRE_BFX':'assets/backfire.bfx'}

def resource_hash(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as f:
        st = os.fstat(f.fileno()); need(stat.S_ISREG(st.st_mode), 'resource not regular')
        h = hashlib.sha256()
        for chunk in iter(lambda:f.read(1048576),b''): h.update(chunk)
        after = os.fstat(f.fileno())
        need((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns) == (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns), 'resource changed during hash')
        return h.hexdigest()

def verified_game_data(path, expected):
    """Require an independently reviewed digest, not the input's self-declared hash."""
    need(re.fullmatch('[0-9a-fA-F]{64}',expected or '') is not None, 'expected game-data SHA-256 is required')
    actual = resource_hash(path)
    need(actual == expected.lower(), 'game-data SHA-256 differs from reviewed digest')
    return actual


def validate_apk(apk, sdk, code, name, certificate, assets, env, cwd):
    need(re.fullmatch('[0-9a-fA-F]{64}',certificate or '') is not None, 'expected certificate SHA-256 is required')
    st = apk.lstat()
    need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size > 0, 'APK is not a nonempty regular unlinked file')
    try:
        with zipfile.ZipFile(apk) as z:
            entries = z.infolist()
            need(bool(entries) and z.testzip() is None, 'APK ZIP CRC failed')
            for asset, (path, expected) in assets.items():
                matches = [entry for entry in entries if entry.filename == asset]
                need(len(matches) == 1 and not matches[0].is_dir(), 'APK asset missing or ambiguous: ' + asset)
                h = hashlib.sha256()
                with z.open(matches[0]) as stream:
                    for chunk in iter(lambda:stream.read(1048576),b''): h.update(chunk)
                need(h.hexdigest() == expected and resource_hash(path) == expected, 'APK asset digest mismatch: ' + asset)
    except (zipfile.BadZipFile, EOFError) as e:
        raise Refusal('invalid APK ZIP') from e
    dirs = [p.name for p in (sdk/'build-tools').iterdir() if p.is_dir()]
    order = subprocess.run(['sort','-V'],input='\n'.join(dirs)+'\n',text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,env=env,cwd=cwd).stdout.splitlines()
    need(bool(order) and order[-1] in dirs, 'no Android build tools')
    bt = sdk/'build-tools'/order[-1]
    subprocess.run([str(bt/'zipalign'),'-c','-P','16','4',str(apk)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,env=env,cwd=cwd)
    badging = subprocess.run([str(bt/'aapt'),'dump','badging',str(apk)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=True,env=env,cwd=cwd).stdout
    match = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'",badging,re.M)
    need(match and match.groups() == ('com.wmmt.fulldata60',code,name), 'APK package or version mismatch')
    result = subprocess.run([str(bt/'apksigner'),'verify','--print-certs',str(apk)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=True,env=env,cwd=cwd).stdout
    certs = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})\s*$',result,re.M)
    need(len(certs) == 1 and certs[0].lower() == certificate.lower(), 'APK certificate mismatch')
    final = apk.lstat()
    need((final.st_dev,final.st_ino,final.st_size,final.st_mtime_ns,final.st_nlink) == (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,1), 'APK changed during validation')


def run(args):
    snapshot = canonical(args.snapshot)
    need(re.fullmatch('[1-9][0-9]*',args.version_code) and int(args.version_code) <= 2100000000, 'invalid version code')
    need(re.fullmatch('[A-Za-z0-9._-]+',args.version_name), 'invalid version name')
    if args.action == 'manifest':
        root, bundle, workspace = map(canonical,(args.root,args.bundle,args.workspace))
        need(snapshot != root and snapshot.is_relative_to(root) and snapshot.stat().st_dev == root.stat().st_dev, 'snapshot must be on the requested image volume')
        need(workspace.is_dir() and workspace != root and workspace.is_relative_to(root) and workspace.stat().st_dev == root.stat().st_dev and not any(c.isspace() for c in str(workspace)), 'workspace must be a directory on the image volume without whitespace')
        need(not workspace.is_relative_to(snapshot), 'workspace cannot equal or be inside snapshot')
        path = Path(args.manifest)
        need(path.is_absolute() and path.parent == workspace and path.name not in ('','.','..'), 'manifest destination must be a direct workspace child')
        need(args.reserve_gib >= 1, 'reserve must be at least 1 GiB')
        validate_volume(root,bundle,args.reserve_gib * 1024**3)
        payload = {'schema':1,'version_code':args.version_code,'version_name':args.version_name,'files':inventory(snapshot)}
        need('build_android.sh' in payload['files'], 'missing build script')
        validate_volume(root,bundle,args.reserve_gib * 1024**3)
        with path.open('x', encoding='utf-8') as f: json.dump(payload,f,indent=2,sort_keys=True); f.write('\n')
        print('Inventory only; caller must independently verify source, rights and version.')
        return
    root, bundle, mp, workspace = map(canonical, (args.root,args.bundle,args.manifest,args.workspace))
    need(snapshot != root and snapshot.is_relative_to(root) and snapshot.stat().st_dev == root.stat().st_dev, 'snapshot must be on the requested image volume')
    need(workspace.is_dir() and workspace != root and workspace.is_relative_to(root) and workspace.stat().st_dev == root.stat().st_dev, 'workspace must be a directory on the requested image volume')
    need(not any(c.isspace() for c in str(workspace)), 'workspace contains whitespace')
    need(not workspace.is_relative_to(snapshot), 'workspace cannot equal or be inside snapshot')
    need(mp.parent == workspace and not mp.is_relative_to(snapshot) and mp.stat().st_dev == root.stat().st_dev, 'manifest must be a direct workspace file outside snapshot')
    need(args.reserve_gib >= 1, 'reserve must be at least 1 GiB')
    need(re.fullmatch('[0-9a-fA-F]{64}',args.expected_cert_sha256 or '') is not None, 'expected certificate SHA-256 is required')
    need(re.fullmatch('[0-9a-fA-F]{64}',args.expected_game_data_sha256 or '') is not None, 'expected game-data SHA-256 is required')
    need(re.fullmatch('[0-9a-fA-F]{64}',getattr(args,'expected_baselines_sha256',None) or '') is not None, 'expected baseline-catalog SHA-256 is required')
    for key in ('_JAVA_OPTIONS','JDK_JAVA_OPTIONS','JAVA_TOOL_OPTIONS'):
        need(key not in os.environ, 'unset ' + key + ' before building')
    for key in ('ANDROID_HOME','JAVA_HOME'):
        v = os.environ.get(key,''); need(v and not any(c.isspace() for c in v), key + ' missing or contains whitespace'); canonical(v)
    ta_rank_inputs=ta_rank_read(os.environ.get('TA_RANK_PRIVATE_INCLUDE'),snapshot)
    vehicle_restore_inputs=vehicle_restore_read(os.environ.get('VEHICLE_RESTORE_PRIVATE_INCLUDE'),snapshot)
    assets = {}
    for key in ('APP_ICON','CARD_RESOURCES','SIGNING_KEYSTORE','GAME_DATA_ZIP','GAME_DATA_BASELINES_ZIP','STORY_CUTIN_BIN','CARD_PAGES_BIN','BACKFIRE_WPK','BACKFIRE_BFX'):
        v = os.environ.get(key,'')
        if key in ('APP_ICON','CARD_RESOURCES','SIGNING_KEYSTORE','GAME_DATA_ZIP','GAME_DATA_BASELINES_ZIP'):
            need(v, key + ' is required')
        if v:
            resource = canonical(v)
            need(resource.is_file() and not resource.is_relative_to(snapshot), key + ' missing or inside snapshot')
            if key in ASSETS:
                if key == 'GAME_DATA_ZIP':
                    digest = verified_game_data(resource,args.expected_game_data_sha256)
                elif key == 'GAME_DATA_BASELINES_ZIP':
                    digest = verified_game_data(resource,args.expected_baselines_sha256)
                else:
                    digest = resource_hash(resource)
                assets[ASSETS[key]] = (resource,digest)
    for key,v in (('VERSION_CODE',args.version_code),('VERSION_NAME',args.version_name)):
        need(not os.environ.get(key) or os.environ[key] == v, key + ' conflicts')
    files = manifest(mp,args.version_code,args.version_name)
    need(all(files.get(path) == digest for path,digest in REVIEWED.items()), 'snapshot script differs from reviewed script pins')
    verify(snapshot,files)
    size = sum(st.st_size for _,st in scan(snapshot).values())
    reserve = args.reserve_gib * 1024**3
    validate_volume(root,bundle,reserve+size)
    work = Path(tempfile.mkdtemp(prefix='android-run-',dir=str(workspace)))
    try:
        copy = work/'snapshot'; shutil.copytree(snapshot,copy,copy_function=shutil.copy2,symlinks=True)
        verify(snapshot,files); verify(copy,files); validate_volume(root,bundle,reserve)
        for d in ('tmp','home','cache'): (work/d).mkdir(mode=0o700)
        out,apk = work/'build',work/'output.apk'
        ta_rank_prepared=ta_rank_publish(ta_rank_inputs,work/'ta-rank-private-input')
        vehicle_restore_prepared=vehicle_restore_publish(vehicle_restore_inputs,work/'vehicle-restore-private-input')
        need(not os.path.lexists(out) and not os.path.lexists(apk), 'output exists')
        env = os.environ.copy(); env.update(BUILD_OUT=str(out),APK_OUT=str(apk),TMPDIR=str(work/'tmp'),TMP=str(work/'tmp'),TEMP=str(work/'tmp'),HOME=str(work/'home'),XDG_CACHE_HOME=str(work/'cache'),JAVA_TOOL_OPTIONS='-Djava.io.tmpdir='+str(work/'tmp'),PYTHONDONTWRITEBYTECODE='1',VERSION_CODE=args.version_code,VERSION_NAME=args.version_name)
        env['TA_RANK_PRIVATE_INCLUDE']=str(ta_rank_prepared)
        env['VEHICLE_RESTORE_PRIVATE_INCLUDE']=str(vehicle_restore_prepared)
        print('Isolated run (volume privacy depends on its mount):',work,flush=True)
        print('External tools may still write system caches; redirection is not a sandbox.',flush=True)
        result = subprocess.run(['/bin/sh',str(copy/'build_android.sh')],cwd=str(copy),env=env)
        need(result.returncode == 0, 'build failed')
        validate_volume(root,bundle,reserve)
        validate_apk(apk,Path(os.environ['ANDROID_HOME']),args.version_code,args.version_name,args.expected_cert_sha256,assets,env,str(work))
        print('Verified explicitly supplied asset digests; optional script fallbacks were not independently verified.')
        validate_volume(root,bundle,reserve)
        print('APK:',apk)
    except Exception:
        print('Run retained:',work,file=sys.stderr); raise

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('manifest','build'))
    p.add_argument('--snapshot',required=True); p.add_argument('--manifest',required=True)
    p.add_argument('--version-code',required=True); p.add_argument('--version-name',required=True)
    p.add_argument('--root'); p.add_argument('--bundle'); p.add_argument('--workspace'); p.add_argument('--reserve-gib',type=int,default=0); p.add_argument('--expected-cert-sha256')
    p.add_argument('--expected-game-data-sha256', help='independently reviewed SHA-256 of GAME_DATA_ZIP; required for build')
    p.add_argument('--expected-baselines-sha256', help='independently reviewed SHA-256 of GAME_DATA_BASELINES_ZIP; required for build')
    args = p.parse_args()
    try:
        need(args.root and args.bundle and args.workspace, 'manifest and build require root, bundle, and workspace')
        run(args)
    except (Refusal,OSError,ValueError,subprocess.SubprocessError,plistlib.InvalidFileException) as e:
        print('Refused:',e,file=sys.stderr); return 1
    return 0
if __name__ == '__main__': sys.exit(main())
