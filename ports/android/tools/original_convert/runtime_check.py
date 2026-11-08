"""Fail closed on incompatible or numerically broken converter runtimes.

Synthetic probes only. No source resource, game state or filesystem is touched.
Passing is a finite self-test, not proof of arbitrary numerical correctness.
"""
import io
import platform
import struct
import sys


class RuntimeCheckError(RuntimeError):
    pass


def _need(condition, message):
    if not condition:
        raise RuntimeCheckError(message)


def _check_numpy(np):
    x = np.array([[1,2,3,1],[4,5,6,1]], dtype=np.float32)
    identity = x @ np.eye(4,dtype=np.float32)
    expected = struct.pack('<8f',1,2,3,1,4,5,6,1)
    _need(identity.dtype == np.dtype('float32') and np.isfinite(identity).all() and
          identity.astype('<f4').tobytes() == expected, 'Broken float32 identity matrix product')
    transform = np.array([[2,0,0,0],[0,4,0,0],[0,0,8,0],[16,32,64,1]],dtype=np.float32)
    translated = x @ transform
    _need(np.isfinite(translated).all() and translated.astype('<f4').tobytes() ==
          struct.pack('<8f',18,40,88,1,24,52,112,1), 'Broken float32 affine matrix product')
    inverse = np.linalg.inv(transform)
    back = translated @ inverse
    _need(np.isfinite(inverse).all() and np.isfinite(back).all() and
          back.astype('<f4').tobytes() == expected, 'Broken float32 inverse transform')
    _need(np.array([0x1234,0xabcd],dtype='<u2').tobytes() == b'\x34\x12\xcd\xab',
          'Unsupported array byte order')
    return {'float32_identity':True,'float32_affine':True,'float32_inverse':True,'little_endian_arrays':True}


def _check_pillow(Image):
    pixels=bytes([255,0,0,255, 0,255,0,255, 0,0,255,255, 128,64,32,255])
    image=Image.frombytes('RGBA',(2,2),pixels)
    stream=io.BytesIO();image.save(stream,format='PNG');stream.seek(0)
    with Image.open(stream) as decoded:
        _need(decoded.size==(2,2) and decoded.convert('RGBA').tobytes()==pixels,
              'PNG codec self-test failed')
    # Original TGA resources use BGR byte order. The top-origin bit is explicit.
    tga=bytearray(18);tga[2]=2;tga[12:16]=struct.pack('<HH',2,2);tga[16]=24;tga[17]=0x20
    tga.extend(bytes([0,0,255, 0,255,0, 255,0,0, 32,64,128]))
    with Image.open(io.BytesIO(tga)) as decoded:
        _need(decoded.size==(2,2) and decoded.convert('RGBA').tobytes()==pixels,
              'TGA colour/order self-test failed')
    jpeg=io.BytesIO();image.convert('RGB').save(jpeg,format='JPEG',quality=100,subsampling=0);jpeg.seek(0)
    with Image.open(jpeg) as decoded:
        _need(decoded.size==(2,2) and decoded.mode=='RGB' and len(decoded.tobytes())==12,
              'JPEG codec self-test failed')
    # A solid red DXT1 block, decoded through the same DDS path as tex.py.
    block=struct.pack('<HHI',0xf800,0,0)
    header=struct.pack('<4s7I44x',b'DDS ',124,0x81007,4,4,8,0,1)
    pf=struct.pack('<2I4s5I',32,4,b'DXT1',0,0,0,0,0)
    caps=struct.pack('<5I',0x1000,0,0,0,0)
    with Image.open(io.BytesIO(header+pf+caps+block)) as decoded:
        _need(decoded.size==(4,4) and decoded.convert('RGBA').tobytes()==bytes([255,0,0,255])*16,
              'DDS DXT1 codec self-test failed')
    return {'png':True,'tga_bgr_top_origin':True,'jpeg':True,'dds_dxt1':True}


def validate_runtime(*, expected_versions=None):
    _need(sys.byteorder=='little' and struct.calcsize('P')==8, 'A little-endian 64-bit runtime is required')
    try:
        import numpy as np
        import PIL
        from PIL import Image
        observed={'python':platform.python_version(),'numpy':np.__version__,'pillow':PIL.__version__}
        if expected_versions is not None:
            _need(isinstance(expected_versions,dict) and set(expected_versions)==set(observed),
                  'A complete signed runtime version profile is required')
            _need(expected_versions==observed,'Converter runtime versions differ from signed recipe')
        numeric=_check_numpy(np)
        codecs=_check_pillow(Image)
    except RuntimeCheckError:
        raise
    except Exception as exc:
        raise RuntimeCheckError('Converter runtime initialization or self-test failed') from exc
    return {'schema':'wmmt-converter-runtime-selfcheck-v1','versions':observed,'numeric':numeric,
            'codecs':codecs,'finite_probe_only':True,'android_execution_claim':False}
