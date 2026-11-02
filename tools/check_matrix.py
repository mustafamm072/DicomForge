"""Run installed-wheel tests in isolated Python environments.

Example: python tools/check_matrix.py --wheel /tmp/dist/dicomforge.whl
  --python /path/to/python3.9 --python /path/to/python3.14 --extras
No interpreter installation, global packages, or Git state is changed.
"""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--python', action='append', required=True)
    parser.add_argument('--extras', action='store_true')
    parser.add_argument('--pydicom', help='Optional pinned pydicom version, e.g. 2.4.4')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    results = []
    with tempfile.TemporaryDirectory(prefix='dicomforge-matrix-') as temp:
        for index, interpreter in enumerate(args.python):
            environment = Path(temp)/str(index)
            subprocess.run([interpreter, '-m', 'venv', str(environment)], check=True)
            python = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                            '--no-deps', str(args.wheel.resolve())], check=True,
                           stdout=subprocess.DEVNULL)
            if args.extras:
                requirements = ['pydicom' + ('==' + args.pydicom if args.pydicom else '>=2.4'),
                                'numpy>=1.23', 'pillow>=10', 'requests>=2.28', 'pynetdicom>=2.0']
                if args.pydicom:
                    # pynetdicom's newer versions require pydicom 3.x.
                    requirements[-1] = 'pynetdicom<3'
                subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                                '--cache-dir', str(Path(temp)/'pip-cache'), *requirements], check=True,
                               stdout=subprocess.DEVNULL)
            env = dict(os.environ)
            env.pop('PYTHONPATH', None)
            env['DICOMFORGE_TEST_INSTALLED'] = '1'
            result = subprocess.run([str(python), '-m', 'unittest'], cwd=root, env=env,
                                    text=True, capture_output=True, timeout=120)
            version = subprocess.check_output([str(python), '--version'], text=True).strip()
            subprocess.run([str(python), '-m', 'dicomforge', '--version'], env=env, check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run([str(environment/('Scripts/dicomforge.exe' if os.name == 'nt' else 'bin/dicomforge')),
                            '--help'], env=env, check=True, stdout=subprocess.DEVNULL)
            subprocess.run([str(python), str(root/'tools/check_package.py')], env=env, check=True,
                           stdout=subprocess.DEVNULL)
            record = {'python': version, 'extras': args.extras, 'exit_code': result.returncode,
                      'output': result.stderr}
            results.append(record)
            args.output.write_text(json.dumps(results, indent=2) + '\n')
            print(f'{version}: {"PASS" if not result.returncode else "FAIL"}', flush=True)
            if result.returncode:
                print(result.stderr, flush=True)
    return int(any(result['exit_code'] for result in results))


if __name__ == '__main__':
    raise SystemExit(main())
