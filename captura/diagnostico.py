"""Preflight sin iniciar reconstrucción ni modificar modelos."""
import importlib.util
import json
import os
from pathlib import Path
import shutil

DEFAULTS = {
    'COLMAP_EXE': r'C:\Mattech\tools\colmap\bin\colmap.exe',
    'OPENMVS_DIR': r'C:\Mattech\tools\openmvs\vc17\x64\Release',
    'BLENDER_EXE': r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe',
    'REALITYSCAN_EXE': r'C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe',
}


def inspect():
    result = {'python_modules': {name: importlib.util.find_spec(name) is not None
                                for name in ['PIL', 'numpy', 'cv2', 'scipy', 'rembg', 'onnxruntime']},
              'tools': {}}
    for key, default in DEFAULTS.items():
        path = os.environ.get(key, default)
        check = Path(path) / 'TextureMesh.exe' if key == 'OPENMVS_DIR' else Path(path)
        result['tools'][key] = {'path': path, 'available': check.is_file() or bool(shutil.which(str(check)))}
    return result


if __name__ == '__main__':
    print(json.dumps(inspect(), ensure_ascii=False, indent=2))
