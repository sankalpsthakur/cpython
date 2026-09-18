"""Prepare and validate the gh-157692 Windows activation regression."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

NEWS = 'Misc/NEWS.d/next/Library/2026-09-18-01-30-00.gh-issue-157692.BatPath.rst'
TEST = '''    @unittest.skipUnless(os.name == 'nt', 'only relevant on Windows')
    def test_activate_bat_preserves_foreign_path(self):
        # gh-157692: cmd.exe and POSIX shells must not share saved PATH state.
        venv.create(self.env_dir)
        activate = self.get_env_file(self.bindir, 'activate.bat')
        deactivate = self.get_env_file(self.bindir, 'deactivate.bat')
        test_batch = self.get_env_file('test_saved_path.bat')
        with open(test_batch, 'w') as f:
            f.write('@echo off\\n'
                    'set "_OLD_VIRTUAL_PATH=/posix/saved/path"\\n'
                    'set "_OLD_VIRTUAL_PATH_BAT="\\n'
                    'path\\n'
                    f'call "{activate}"\\n'
                    'path\\n'
                    f'call "{activate}"\\n'
                    'path\\n'
                    f'call "{deactivate}"\\n'
                    'path\\n'
                    'echo FOREIGN:%_OLD_VIRTUAL_PATH%\\n')
        out, err = check_output([test_batch], encoding='oem')
        paths = [line.partition('=')[2] for line in out.splitlines()
                 if line.upper().startswith('PATH=')]
        self.assertEqual(len(paths), 4, out)
        original, active, repeated, restored = paths
        self.assertEqual(active,
                         os.path.join(self.env_dir, self.bindir) + ';' + original)
        self.assertEqual(repeated, active)
        self.assertEqual(restored, original)
        self.assertIn('FOREIGN:/posix/saved/path', out.splitlines())

'''

def checked_read(path, sha):
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD:' + path], text=True).strip()
    if actual != sha:
        raise RuntimeError(f'Unexpected baseline: {path}: {actual}')
    return Path(path).read_text(encoding='utf-8')


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Nonunique replacement anchor')
    return text.replace(old, new, 1)


def prepare(phase):
    if phase == 'tests':
        path = 'Lib/test/test_venv.py'
        text = checked_read(path, '2f30d3108021dc66eec6508e27adfc63c2c4fd8c')
        anchor = "    @unittest.skipUnless(os.name == 'nt', 'only relevant on Windows')\n    def test_unicode_in_batch_file(self):"
        Path(path).write_text(replace_once(text, anchor, TEST + anchor), encoding='utf-8')
    else:
        for path, sha in (
            ('Lib/venv/scripts/nt/activate.bat', '4a3e791abb86bd27da3442cd05cd37853a690f8a'),
            ('Lib/venv/scripts/nt/deactivate.bat', '4a04fb7c0bed44bd5a5d42b3f49ef6ad4f6d6e97'),
        ):
            text = checked_read(path, sha)
            if '_OLD_VIRTUAL_PATH_BAT' in text or '_OLD_VIRTUAL_PATH' not in text:
                raise RuntimeError('Unexpected activation variables')
            Path(path).write_text(text.replace('_OLD_VIRTUAL_PATH', '_OLD_VIRTUAL_PATH_BAT'), encoding='utf-8')
        Path(NEWS).write_text(
            'Use separate saved ``PATH`` state for the Windows batch activation\n'
            'scripts in :mod:`venv`. This prevents a POSIX shell started from an\n'
            'activated command prompt from restoring a Windows-format ``PATH``\n'
            'when it activates a virtual environment.\n', encoding='utf-8')


def bash_repro():
    if os.name != 'nt':
        raise RuntimeError('This reproducer requires native Windows')
    bash = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe'
    if not bash.is_file():
        raise RuntimeError(f'Git Bash not found: {bash}')
    import venv
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        envdir = root / 'venv'
        venv.create(envdir)
        script = root / 'probe.sh'
        script.write_text('''set -eu
# Git Bash supplies POSIX utilities in addition to the inherited Windows PATH.
export PATH="/usr/bin:/bin:$PATH"
previous_path=$PATH
activate=$(cygpath -u "$1")/Scripts/activate
. "$activate"
command -v uname >/dev/null
command -v cygpath >/dev/null
deactivate
test "$PATH" = "$previous_path"
printf 'BASH_PATH_RESTORED\\n'
''', encoding='utf-8', newline='\n')
        batch = root / 'probe.cmd'
        batch.write_text(
            '@echo off\nset "_OLD_VIRTUAL_PATH="\nset "_OLD_VIRTUAL_PATH_BAT="\n'
            f'call "{envdir / "Scripts/activate.bat"}"\n'
            f'"{bash}" --noprofile --norc "{script.as_posix()}" "{envdir}"\n'
            'exit /b %errorlevel%\n', encoding='utf-8')
        proc = subprocess.run([os.environ['COMSPEC'], '/d', '/c', str(batch)],
                              capture_output=True, timeout=30)
        sys.stdout.buffer.write(proc.stdout)
        sys.stderr.buffer.write(proc.stderr)
        if proc.returncode:
            raise RuntimeError(f'Git Bash activation failed: {proc.returncode}')
        if b'BASH_PATH_RESTORED' not in proc.stdout:
            raise RuntimeError('Git Bash did not complete the checks')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('tests', 'fix', 'bash'))
    phase = parser.parse_args().phase
    if phase == 'bash':
        bash_repro()
    else:
        prepare(phase)
