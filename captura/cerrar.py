"""Compatibilidad de CLI: conserva la malla sin reconstruirla como relieve XY.
Uso: python captura/cerrar.py entrada.ply salida.ply [camaras.json]
No cierra agujeros ni inventa geometría. AR admite superficies abiertas.
Para una reparación local, seleccionar manualmente el borde inferior y trabajar en una copia.
La implementación antigua está en respaldo_antes_captura_inteligente/.
"""
from pathlib import Path
import argparse
import shutil


def conservar(src, dst):
    source, target = Path(src).resolve(), Path(dst).resolve()
    if source == target:
        raise ValueError('La salida debe ser otra ruta para conservar el original')
    if target.exists():
        raise FileExistsError(f'No se sobrescribe una malla existente: {target}')
    with source.open('rb') as data:
        if data.read(3) != b'ply':
            raise ValueError('Entrada no es PLY')
    shutil.copy2(source, target)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('src')
    parser.add_argument('dst')
    parser.add_argument('cameras', nargs='?')
    args = parser.parse_args()
    print('Geometría intacta, sin cierre global:', conservar(args.src, args.dst))
