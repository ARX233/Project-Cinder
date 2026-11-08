import hashlib, importlib.util, json, os, tempfile, unittest, zipfile, shutil
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('external_snapshot_build',Path(__file__).with_name('external_snapshot_build.py'))
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def setUp(self):
        # Keep even simulated package fixtures in the requested external workspace.
        fixture_parent=Path(os.environ.get('TMPDIR','/Volumes/CodexWork')).resolve()
        if not fixture_parent.is_relative_to(Path('/Volumes/CodexWork').resolve()):
            raise RuntimeError('Set TMPDIR under /Volumes/CodexWork for host fixtures')
        self.tmp=tempfile.TemporaryDirectory(dir=fixture_parent)
        self.p=Path(self.tmp.name).resolve(); self.src=self.p/'snapshot'; self.src.mkdir()
        (self.src/'build_android.sh').write_text('#!/bin/sh\nprintf x > "$APK_OUT"\nprintf "%s\\n%s\\n%s\\n%s\\n%s\\n%s" "$BUILD_OUT" "$TMPDIR" "$HOME" "$XDG_CACHE_HOME" "$JAVA_TOOL_OPTIONS" "$VERSION_CODE" > "$HOME/observed"\nprintf changed > build_android.sh\n')
        (self.src/'input.c').write_text('source')
        self.files=m.inventory(self.src); self.mp=self.p/'manifest.json'
        self.mp.write_text(json.dumps({'schema':1,'version_code':'42','version_name':'v1','files':self.files}))
    def tearDown(self): self.tmp.cleanup()
    def test_manifest_and_changes(self):
        files=m.manifest(self.mp,'42','v1'); m.verify(self.src,files)
        with self.assertRaises(m.Refusal): m.manifest(self.mp,'43','v1')
        (self.src/'extra').write_text('x')
        with self.assertRaises(m.Refusal): m.verify(self.src,files)
        (self.src/'extra').unlink(); (self.src/'input.c').write_text('changed')
        with self.assertRaises(m.Refusal): m.verify(self.src,files)
        (self.src/'input.c').unlink()
        with self.assertRaises(m.Refusal): m.verify(self.src,files)
    def test_dangerous_entries(self):
        for kind in ('symlink','key'):
            f=self.src/('private.pem' if kind=='key' else 'bad')
            if kind=='symlink': f.symlink_to('input.c')
            elif kind=='hardlink': os.link(self.src/'input.c',f)
            elif kind=='fifo': os.mkfifo(f)
            else: f.write_text('private')
            with self.assertRaises(m.Refusal): m.inventory(self.src)
            f.unlink()
    def test_hardlink_and_special_stat_mock(self):
        import types, stat
        st=(self.src/'input.c').stat()
        for mode,nlink in ((stat.S_IFREG,2),(stat.S_IFIFO,1)):
            entry=types.SimpleNamespace(name='fake',path=str(self.src/'fake'),stat=lambda follow_symlinks: types.SimpleNamespace(st_dev=st.st_dev,st_mode=mode,st_nlink=nlink))
            class Entries:
                def __enter__(self): return iter([entry])
                def __exit__(self,*args): pass
            with patch.object(m.os,'scandir',return_value=Entries()):
                with self.assertRaises(m.Refusal): m.scan(self.src)
    def test_manifest_escape_and_duplicates(self):
        doc={'schema':1,'version_code':'42','version_name':'v1','files':{'build_android.sh':'a'*64,'../escape':'a'*64}}
        self.mp.write_text(json.dumps(doc))
        with self.assertRaises(m.Refusal): m.manifest(self.mp,'42','v1')
        self.mp.write_text('{"schema":1,"schema":1}')
        with self.assertRaises(m.Refusal): m.manifest(self.mp,'42','v1')
    def test_simulated_build_isolated(self):
        root=self.p; workspace=self.p/'work'; workspace.mkdir(); bundle=self.p/'disk.sparsebundle'; bundle.mkdir()
        external_manifest=self.mp; self.mp=workspace/'manifest.json'; shutil.copy2(external_manifest,self.mp)
        sdk=self.p/'sdk'; java=self.p/'java'; sdk.mkdir(); java.mkdir()
        icon=self.p/'icon'; card=self.p/'card'; key=self.p/'keystore'; data=self.p/'data.zip'; baseline=self.p/'data-baselines.zip'
        for f in (icon,card,key,data,baseline): f.write_text('dummy')
        class Args: pass
        a=Args(); a.action='build'; a.snapshot=str(self.src); a.manifest=str(self.mp); a.root=str(root); a.bundle=str(bundle); a.workspace=str(workspace); a.reserve_gib=1; a.version_code='42'; a.version_name='v1'; a.expected_cert_sha256='a'*64; a.expected_game_data_sha256=hashlib.sha256(data.read_bytes()).hexdigest()
        with self.assertRaisesRegex(m.Refusal,'game-data SHA-256 differs'): m.verified_game_data(data,'0'*64)
        with self.assertRaisesRegex(m.Refusal,'expected game-data SHA-256'): m.verified_game_data(data,'')
        self.assertEqual(m.verified_game_data(data,a.expected_game_data_sha256),a.expected_game_data_sha256)
        a.expected_baselines_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest()
        env={'ANDROID_HOME':str(sdk),'JAVA_HOME':str(java),'APP_ICON':str(icon),'CARD_RESOURCES':str(card),'SIGNING_KEYSTORE':str(key),'GAME_DATA_ZIP':str(data),'GAME_DATA_BASELINES_ZIP':str(baseline)}
        with patch.dict(os.environ,env,clear=True), patch.object(m,'validate_volume'):
            catalog_pin=a.expected_baselines_sha256
            a.expected_baselines_sha256=''
            with self.assertRaisesRegex(m.Refusal,'expected baseline-catalog'): m.run(a)
            a.expected_baselines_sha256='0'*64
            with self.assertRaisesRegex(m.Refusal,'SHA-256 differs'): m.run(a)
            a.expected_baselines_sha256=catalog_pin
            with patch.dict(os.environ,{'GAME_DATA_BASELINES_ZIP':''}):
                with self.assertRaisesRegex(m.Refusal,'GAME_DATA_BASELINES_ZIP is required'): m.run(a)
            # Caller-authored build script is not in the reviewed allowlist.
            with self.assertRaises(m.Refusal): m.run(a)
            original=(self.src/'build_android.sh').read_bytes()
            old_script=Path(__file__).resolve().parents[3]/'build_android.sh'
            (self.src/'build_android.sh').write_bytes(old_script.read_bytes())
            old_files=m.inventory(self.src)
            self.mp.write_text(json.dumps({'schema':1,'version_code':'42','version_name':'v1','files':old_files}))
            with self.assertRaisesRegex(m.Refusal,'reviewed script'): m.run(a)
            (self.src/'build_android.sh').write_bytes(original)
            self.mp.write_text(json.dumps({'schema':1,'version_code':'42','version_name':'v1','files':self.files}))
        tools=sdk/'build-tools'/'1'; tools.mkdir(parents=True)
        seen=[]
        def fake_run(command,**kw):
            self.assertEqual(kw['env']['PYTHONDONTWRITEBYTECODE'],'1')
            self.assertNotIn('_JAVA_OPTIONS',kw['env']); self.assertNotIn('JDK_JAVA_OPTIONS',kw['env'])
            if command[0]!='/bin/sh':
                seen.append(command[0].split('/')[-1])
                self.assertEqual(kw['cwd'],str(Path(kw['env']['HOME']).parent))
                for var in ('TMPDIR','TMP','TEMP','HOME','XDG_CACHE_HOME'):
                    self.assertTrue(Path(kw['env'][var]).is_relative_to(Path(kw['cwd'])))
                self.assertEqual(kw['env']['JAVA_TOOL_OPTIONS'],'-Djava.io.tmpdir='+kw['env']['TMPDIR'])
            if command[0]=='/bin/sh':
                e=kw['env']; out=Path(e['APK_OUT'])
                with zipfile.ZipFile(out,'w') as z:
                    z.writestr('assets/re3dxplus-data.zip',Path(e['GAME_DATA_ZIP']).read_bytes())
                    z.writestr('assets/card-resources-v1.zip',Path(e['CARD_RESOURCES']).read_bytes())
                    z.writestr('assets/data-baselines.zip',Path(e['GAME_DATA_BASELINES_ZIP']).read_bytes())
                (Path(e['HOME'])/'observed').write_text('\n'.join(e[k] for k in ('BUILD_OUT','TMPDIR','HOME','XDG_CACHE_HOME','JAVA_TOOL_OPTIONS','VERSION_CODE')))
                (Path(kw['cwd'])/'build_android.sh').write_text('changed')
                return SimpleNamespace(returncode=0)
            if command[0]=='sort': return SimpleNamespace(stdout='1\n')
            if command[0].endswith('/zipalign'):
                self.assertEqual(command[1:5],['-c','-P','16','4']); return SimpleNamespace(stdout='')
            if command[0].endswith('/aapt'): return SimpleNamespace(stdout="package: name='com.wmmt.fulldata60' versionCode='42' versionName='v1'\n")
            if command[0].endswith('/apksigner'): return SimpleNamespace(stdout='Signer #1 certificate SHA-256 digest: '+ 'a'*64+'\n')
            raise AssertionError(command)
        archive=workspace/'archive'/'tree'; archive.parent.mkdir(); shutil.copytree(self.src,archive)
        a.snapshot=str(archive)
        with patch.dict(os.environ,env,clear=True), patch.object(m,'validate_volume'), patch.object(m,'REVIEWED',{'build_android.sh':self.files['build_android.sh']}), patch.object(m.subprocess,'run',side_effect=fake_run):
            m.run(a)
        self.assertEqual(seen,['sort','zipalign','aapt','apksigner'])
        self.assertEqual(m.inventory(archive),self.files)
        a.manifest=str(external_manifest)
        with patch.dict(os.environ,env,clear=True), patch.object(m,'validate_volume'):
            with self.assertRaisesRegex(m.Refusal,'manifest must'): m.run(a)
        a.manifest=str(self.mp)
        self.assertEqual(hashlib.sha256((self.src/'build_android.sh').read_bytes()).hexdigest(),self.files['build_android.sh'])
        runs=list(workspace.glob('android-run-*')); self.assertEqual(len(runs),1); self.assertTrue(zipfile.is_zipfile(runs[0]/'output.apk'))
        self.assertEqual((runs[0]/'snapshot/build_android.sh').read_text(),'changed')
        observed=(runs[0]/'home/observed').read_text()
        self.assertNotIn('do-not-expose',observed); self.assertIn('-Djava.io.tmpdir='+str(runs[0]/'tmp'),observed)
        for key in ('_JAVA_OPTIONS','JDK_JAVA_OPTIONS','JAVA_TOOL_OPTIONS'):
            for value in ('', '-Djava.io.tmpdir=/internal'):
                with patch.dict(os.environ,{**env,key:value},clear=True), patch.object(m,'validate_volume'):
                    with self.assertRaisesRegex(m.Refusal,'unset '+key): m.run(a)
        with patch.dict(os.environ,{**env,'VERSION_CODE':'99'},clear=True), patch.object(m,'validate_volume'):
            with self.assertRaises(m.Refusal): m.run(a)
        with patch.dict(os.environ,{**env,'JAVA_HOME':str(self.p/'bad path')},clear=True), patch.object(m,'validate_volume'):
            with self.assertRaises(m.Refusal): m.run(a)
        with patch.dict(os.environ,{k:v for k,v in env.items() if k!='GAME_DATA_ZIP'},clear=True), patch.object(m,'validate_volume'):
            with self.assertRaisesRegex(m.Refusal,'GAME_DATA_ZIP'): m.run(a)
        inside=archive/'nested'; inside.mkdir()
        for bad_workspace in (archive,inside,root,bundle.parent.parent):
            a.workspace=str(bad_workspace)
            with patch.dict(os.environ,env,clear=True), patch.object(m,'validate_volume'):
                with self.assertRaises(m.Refusal): m.run(a)
        a.workspace=str(workspace); a.snapshot=str(bundle.parent.parent)
        with patch.dict(os.environ,env,clear=True), patch.object(m,'validate_volume'):
            with self.assertRaisesRegex(m.Refusal,'snapshot must'): m.run(a)
    def test_manifest_only_external_workspace(self):
        root=self.p; workspace=self.p/'work'; workspace.mkdir(); bundle=self.p/'disk.sparsebundle'; bundle.mkdir()
        archive=workspace/'archive'/'tree'; archive.parent.mkdir(); shutil.copytree(self.src,archive)
        args=SimpleNamespace(action='manifest',snapshot=str(archive),manifest=str(workspace/'manifest.json'),root=str(root),bundle=str(bundle),workspace=str(workspace),reserve_gib=1,version_code='42',version_name='v1')
        with patch.object(m,'validate_volume'):
            m.run(args)
            self.assertEqual(m.manifest(Path(args.manifest),'42','v1'),self.files)
            with self.assertRaises(FileExistsError): m.run(args)
            args.manifest=str(self.p/'elsewhere.json')
            with self.assertRaises(m.Refusal): m.run(args)
            args.workspace=str(archive); args.manifest=str(archive/'manifest.json')
            with self.assertRaises(m.Refusal): m.run(args)
            args.workspace=str(workspace); args.manifest=str(workspace/'new.json'); args.snapshot=str(self.p.parent)
            with self.assertRaisesRegex(m.Refusal,'snapshot must'): m.run(args)
    def test_apk_verification(self):
        apk=self.p/'test.apk'; sdk=self.p/'sdk'; (sdk/'build-tools'/'1').mkdir(parents=True)
        apk.write_bytes(b'')
        with self.assertRaises(m.Refusal): m.validate_apk(apk,sdk,'42','v1','a'*64,{}, {}, str(self.p))
        apk.write_bytes(b'x')
        with self.assertRaises(m.Refusal): m.validate_apk(apk,sdk,'42','v1','a'*64,{}, {}, str(self.p))
        with zipfile.ZipFile(apk,'w',compression=zipfile.ZIP_STORED) as z: z.writestr('x','payloadxyz')
        good=apk.read_bytes(); apk.write_bytes(good.replace(b'payloadxyz',b'payloadxyZ'))
        with self.assertRaises(m.Refusal): m.validate_apk(apk,sdk,'42','v1','a'*64,{}, {}, str(self.p))
        apk.write_bytes(good)
        def responses(package='com.wmmt.fulldata60',version='42',cert='a'*64):
            return [SimpleNamespace(stdout='1\n'),SimpleNamespace(stdout=''),SimpleNamespace(stdout=f"package: name='{package}' versionCode='{version}' versionName='v1'\n"),SimpleNamespace(stdout='Signer #1 certificate SHA-256 digest: '+cert+'\n')]
        with patch.object(m.subprocess,'run',side_effect=responses()): m.validate_apk(apk,sdk,'42','v1','a'*64,{}, {}, str(self.p))
        for outputs in (responses(package='wrong'),responses(version='43'),responses(cert='b'*64)):
            with patch.object(m.subprocess,'run',side_effect=outputs):
                with self.assertRaises(m.Refusal): m.validate_apk(apk,sdk,'42','v1','a'*64,{}, {}, str(self.p))
    def test_assets_and_zipalign(self):
        import subprocess
        apk=self.p/'out.apk'; sdk=self.p/'sdk'; (sdk/'build-tools'/'1').mkdir(parents=True)
        source=self.p/'payload'; source.write_bytes(b'input')
        assets={'assets/re3dxplus-data.zip':(source,m.resource_hash(source))}
        def pack(value=b'input'):
            with zipfile.ZipFile(apk,'w') as z: z.writestr('assets/re3dxplus-data.zip',value)
        good=[SimpleNamespace(stdout='1\n'),SimpleNamespace(stdout=''),SimpleNamespace(stdout="package: name='com.wmmt.fulldata60' versionCode='42' versionName='v1'"),SimpleNamespace(stdout='Signer #1 certificate SHA-256 digest: '+'a'*64)]
        pack()
        with patch.object(m.subprocess,'run',side_effect=good): m.validate_apk(apk,sdk,'42','v1','a'*64,assets,{},str(self.p))
        pack(b'changed')
        with self.assertRaisesRegex(m.Refusal,'asset digest'): m.validate_apk(apk,sdk,'42','v1','a'*64,assets,{},str(self.p))
        with zipfile.ZipFile(apk,'w') as z: z.writestr('other','input')
        with self.assertRaisesRegex(m.Refusal,'asset missing'): m.validate_apk(apk,sdk,'42','v1','a'*64,assets,{},str(self.p))
        pack()
        with patch.object(m.subprocess,'run',side_effect=[SimpleNamespace(stdout='1\n'),subprocess.CalledProcessError(1,'zipalign')]):
            with self.assertRaises(subprocess.CalledProcessError): m.validate_apk(apk,sdk,'42','v1','a'*64,assets,{},str(self.p))
    def test_volume_chain_and_space(self):
        root=self.p/'root'; root.mkdir(); bundle=self.p/'disk.sparsebundle'; bundle.mkdir()
        vol={'MountPoint':str(root),'FilesystemType':'apfs','BusProtocol':'Disk Image','WritableVolume':True,'WritableMedia':True,'APFSPhysicalStores':[{'APFSPhysicalStore':'disk5s2'}],'DeviceIdentifier':'disk6s1','APFSContainerFree':99999999}
        image={'image-path':str(bundle),'image-type':'sparse bundle disk image','writeable':True,'system-entities':[{'dev-entry':'/dev/disk5s2'},{'dev-entry':'/dev/disk6s1','mount-point':str(root)}]}
        host={'MountPoint':str(self.p),'Internal':False,'WritableVolume':True,'WritableMedia':True,'BusProtocol':'USB','ParentWholeDisk':'disk4'}
        disk={'WholeDisk':True,'VirtualOrPhysical':'Physical','Internal':False,'WritableMedia':True,'BusProtocol':'USB'}
        from types import SimpleNamespace
        def exercise():
            with patch.object(m,'mount_of',return_value=self.p), patch.object(m,'system_plist',side_effect=[vol,{'images':[image]},host,disk]), patch.object(m.os,'statvfs',return_value=SimpleNamespace(f_bavail=1000,f_frsize=4096)):
                m.validate_volume(root,bundle,1)
        exercise()
        for obj,key,bad in ((vol,'APFSContainerFree',0),(vol,'WritableVolume',False),(image,'writeable',False),(image,'image-path','wrong'),(host,'Internal',True),(disk,'BusProtocol','Disk Image')):
            old=obj[key]; obj[key]=bad
            with self.assertRaises(m.Refusal): exercise()
            obj[key]=old
    def test_bad_volume_fails(self):
        root=self.p/'root'; root.mkdir(); bundle=self.p/'disk.sparsebundle'; bundle.mkdir()
        with patch.object(m,'system_plist',return_value={'MountPoint':str(root),'FilesystemType':'apfs','BusProtocol':'USB'}):
            with self.assertRaises(m.Refusal): m.validate_volume(root,bundle,1)

if __name__=='__main__': unittest.main()
