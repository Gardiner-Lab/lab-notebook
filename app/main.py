"""
Lab Notebook: the Gardiner Lab suite's digital lab notebook.

Everyone keeps a notebook of days and pages; protocols are shared in a library
anyone can use; plasmids link to the Plasmid Editor and MoClo reactions come
in as active tables. Its design follows Trilium (TriliumNext,
https://github.com/TriliumNext/Trilium); see NOTICE.
"""

import os

from flask import Flask, redirect, render_template, request

APP_VERSION = '0.4.1'


class PrefixMiddleware:
    """Mount the app under URL_PREFIX (/notebook), as the suite's proxy passes the full path."""

    def __init__(self, wsgi_app, prefix: str):
        self.wsgi_app = wsgi_app
        self.prefix = '/' + prefix.strip('/')

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path == self.prefix or path.startswith(self.prefix + '/'):
            environ['SCRIPT_NAME'] = environ.get('SCRIPT_NAME', '') + self.prefix
            environ['PATH_INFO'] = path[len(self.prefix):] or '/'
        return self.wsgi_app(environ, start_response)


def create_app() -> Flask:
    from app import db, people, sources
    from app.api import api

    app = Flask(__name__)
    # Room for several photos at once; each file is limited to 25 MB (app/attachments.py).
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024
    db.initialize(os.environ.get('NOTEBOOK_DATABASE_PATH', '/notebook/notebook.db'))
    sources.seed_library()
    sources.fill_search_text()
    app.register_blueprint(api, url_prefix='/api')

    def links() -> dict:
        return {
            'suite_home': os.environ.get('SUITE_HOME_URL', '/'),
            'editor': os.environ.get('EDITOR_URL', '/editor').rstrip('/'),
            'moclo': os.environ.get('MOCLO_URL', '/').rstrip('/'),
            'seeds': os.environ.get('SEEDS_URL', '/seeds').rstrip('/'),
            'logout': os.environ.get('SUITE_LOGOUT_URL', '/account/logout'),
        }

    @app.route('/')
    def notebook_page():
        person = people.current()
        if person is None:
            login = os.environ.get('SUITE_LOGIN_URL', '/account/login')
            return redirect(f'{login}?next={request.script_root}/')
        return render_template('notebook.html', version=APP_VERSION, person=person, links=links())

    @app.route('/about')
    def about_page():
        return render_template('about.html', version=APP_VERSION, links=links())

    @app.route('/health')
    def health():
        return {'status': 'healthy', 'version': APP_VERSION}

    prefix = os.environ.get('URL_PREFIX', '').strip('/')
    if prefix:
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix)
    return app


app = create_app() if os.environ.get('NOTEBOOK_NO_APP') != '1' else None

if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=int(os.environ.get('PORT', 5004)), debug=True)
