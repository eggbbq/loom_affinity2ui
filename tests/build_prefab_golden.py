"""Developer-only fixture builder for comparison with the previous serializer.

It reads a supplied historical wheel into a temporary alias package. Neither
the exporter nor its tests install/import the psd2ui distribution at runtime.
"""
import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

from PIL import Image


def layout_fixture():
    def node(kind, name, position, size, **values):
        return dict(type=kind,name=name,position=position,size=size,visible=True,**values)
    title=node('text','title',[3,4],[100,24],text='开始\nStart',font='Arial',fontSize=18,
        align='center',opacity=.75,color='#ffeedd',outline=2,outlineColor='#112233',
        shadow=[1.5,-2],shadowColor='#000000',shadowBlur=3)
    return dict(version=1,**node('root','CompatibilityPanel',[0,0],[320,240],children=[
        node('image','background',[0,0],[16,12],asset='parts/background.png'),
        node('container','btn_start',[10,20],[120,40],component='GButton',opacity=.5,children=[
            node('image','bg',[0,0],[16,12],asset='parts/background.png'),title]),
        node('image','icon_coin',[140,20],[16,16],component='GLoader',asset='icons/coin.png'),
        node('text','input_text',[10,80],[160,40],component='GTextInput',text='one\ntwo',font='Arial',
             fontSize=16,align='right',color='#123456',outline=1),
        node('container','hbox_actions',[10,140],[200,40],component='hbox',children=[
            node('text','second',[80,0],[40,20],text='二',fontSize=14),
            node('text','first',[0,0],[40,20],text='一',fontSize=14)]),
    ]))


def create_inputs(base):
    source=base/'source';project=base/'project'
    (source/'parts').mkdir(parents=True);(source/'icons').mkdir()
    project.mkdir()
    Image.new('RGBA',(16,12),(10,30,80,255)).save(source/'parts/background.png')
    Image.new('RGBA',(16,16),(200,180,10,255)).save(source/'icons/coin.png')
    layout=layout_fixture();path=source/'layout.json';path.write_text(json.dumps(layout,ensure_ascii=False))
    return path,project


def read_generated(project):
    return {path.relative_to(project).as_posix():path.read_text(encoding='utf-8')
            for path in sorted(project.rglob('*')) if path.is_file() and path.suffix in ('.lh','.ls','.meta')}


def run_case(compiler, root, mode):
    path,project=create_inputs(root)
    if mode=='preserved':
        target=project/'assets/ui/parts/background.png.meta';target.parent.mkdir(parents=True)
        target.write_text(json.dumps({'uuid':'11111111-1111-4111-8111-111111111111','custom':'keep',
            'importer':{'textureType':2,'filterMode':0,'sRGB':False,'sizeGrid':[1,2,3,4,0]}}))
        prefab_meta=project/'assets/ui/CompatibilityPanel.lh.meta'
        prefab_meta.write_text(json.dumps({'uuid':'22222222-2222-4222-8222-222222222222','custom':'prefab'}))
        scene=project/'assets/Test.ls'
        scene.write_text(json.dumps({'_$type':'Scene','_$id':'scene','_$child':[
            {'_$id':'existing-instance','_$prefab':'old','x':23,'visible':False}],
            '_$comp':[{'_$type':'Main'},{'_$type':'OtherScript'}]}))
        compiler.generate_prefab(path,project,'assets/ui/CompatibilityPanel.lh','assets/Test.ls',
                                 preserve_resource_paths=True,scene_instance_id='existing-instance')
    else:
        compiler.generate_prefab(path,project)
    return read_generated(project)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-wheel',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'fixtures/legacy_prefab_v1.json')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);package=root/'legacy_fixture_backend';package.mkdir()
        (package/'__init__.py').write_text('')
        with zipfile.ZipFile(args.legacy_wheel) as archive:
            for name in ('laya_prefab.py','laya_types.py','naming.py','layout.py','deduplication.py'):
                (package/name).write_bytes(archive.read('psd2ui/'+name))
        sys.path.insert(0,str(root))
        compiler=importlib.import_module('legacy_fixture_backend.laya_prefab')
        result={'originWheelSha256':hashlib.sha256(args.legacy_wheel.read_bytes()).hexdigest(),
                'layout':layout_fixture(),'cases':{}}
        for mode in ('default','preserved'):
            directory=root/mode;directory.mkdir()
            result['cases'][mode]=run_case(compiler,directory,mode)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(args.output)


if __name__=='__main__':main()
