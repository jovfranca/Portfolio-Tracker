"""Brand checks run in the normal pytest suite without a frontend toolchain."""
from hashlib import sha256
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_identity_exports_are_used_unchanged():
    # SHA-256 of original exports from the supplied Quintrion_Vector_Identity.zip.
    canonical = {
        'quintrion_app_icon_navy.svg': 'c812a2943a19ebc0b3fa8a85ecc312a3a423a87a73d738e6d131cecd28cb55d7',
        'quintrion_favicon.ico': 'a02468a22449dfeaed55de3965a08be979e4a1920b55b128c11ea04f3672e5b7',
        'quintrion_horizontal_master_dark.svg': 'aef0ff3103316618123cc59cc3c2cc2392ec2fff1852df786d7da972d7797a7c',
        'quintrion_horizontal_master_light.svg': '7f7a9949e578655f025a54f37838fe4c98d24c02000bc7e8043a9504aee6a659',
        'quintrion_horizontal_portuguese_light.svg': '983d19256136e8cc0c13d0f064c725e3895e6ab5d735d211bf2ced4e525923da',
        'quintrion_symbol_small.svg': '5579b19250d5e0aa6eed26ac39bcc3ff0c0452cc0dfffaa0210742e8b9458a9e',
    }
    for name, digest in canonical.items():
        assert sha256((ROOT / 'frontend/public/brand' / name).read_bytes()).hexdigest() == digest
    shell = (ROOT / 'frontend/src/AppShell.tsx').read_text(encoding='utf-8-sig')
    assert '/brand/quintrion_horizontal_master_dark.svg' in shell
    assert 'quintrion_favicon.ico' in (ROOT / 'frontend/index.html').read_text(encoding='utf-8-sig')


def test_ui_has_no_legacy_brand_outside_explicit_protocol_compatibility():
    paths = list((ROOT / 'frontend/src').glob('*')) + [ROOT / 'frontend/index.html']
    exceptions = {
        'api.ts': "  const headers: Record<string, string> = { 'X-Aurion-Request': '1' }",
        'AuthShell.tsx': "    const remembered = Number(localStorage.getItem('quintrion-household') ?? localStorage.getItem('aurion-household'))",
    }
    for path in paths:
        if path.is_file():
            text = path.read_text(encoding='utf-8-sig').replace(exceptions.get(path.name, '\0'), '')
            assert not re.search(r'aurion|portfolio[ -]tracker', text, re.I), path.name
    css = (ROOT / 'frontend/src/theme.css').read_text(encoding='utf-8-sig')
    for color in ['#0B1F3B', '#0E7C86', '#22D3A1', '#E8F9F3', '#D4A574']:
        assert color in css
    assert 'Manrope' in css and 'Inter' in css
