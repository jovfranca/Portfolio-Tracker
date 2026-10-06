"""Interactive, loopback-only API startup; ordinary Uvicorn keeps secure defaults."""
import getpass
import os
import warnings

import uvicorn

from src.auth.service import dev_enabled


def main():
    if not dev_enabled() and not os.getenv('GOOGLE_CLIENT_ID', '').strip():
        print('Nenhum login configurado. Escolha uma chave para o login local nesta execucao.')
        try:
            with warnings.catch_warnings():
                # Never allow getpass to fall back to echoing credentials.
                warnings.simplefilter('error', getpass.GetPassWarning)
                key = getpass.getpass('Chave de desenvolvimento (entrada oculta): ')
        except (getpass.GetPassWarning, EOFError):
            raise SystemExit('Use um terminal interativo ou configure o login em docs/authentication.md.') from None
        if not key.strip():
            raise SystemExit('A chave de desenvolvimento nao pode ser vazia.')
        if len(key) > 1024:
            raise SystemExit('A chave de desenvolvimento deve ter no maximo 1024 caracteres.')
        os.environ['DEV_AUTH_ENABLED'] = '1'
        os.environ['DEV_AUTH_TOKEN'] = key

    # This entry point always binds HTTP to loopback. These settings affect only
    # this Python process, never the caller's environment or the private .env.
    os.environ['SESSION_COOKIE_SECURE'] = '0'
    if dev_enabled():
        print('Login local: usuario local. Use a chave de desenvolvimento no navegador.')
    uvicorn.run('src.main:app', host='127.0.0.1', port=8000)


if __name__ == '__main__':
    main()
