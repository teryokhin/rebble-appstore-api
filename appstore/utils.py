import os
import random
import time
from typing import Dict, Optional
from uuid import getnode

import requests
from flask import request, abort, url_for

from .settings import config
from appstore.models import App, AssetCollection, CompanionApp


parent_app = None

class ObjectIdGenerator:
    def __init__(self):
        self.counter = random.randint(0, 0xFFFFFF)
        self.node_id = getnode() % 0xFFFFFF
        self.pid = os.getpid() % 0xFFFF

    def generate(self):
        self.counter = (self.counter + 1) % 0xFFFFFF
        return f'{(int(time.time()) % 0xFFFFFFFF):08x}{self.node_id:06x}{self.pid:04x}{self.counter:06x}'


id_generator = ObjectIdGenerator()

plat_dimensions = {
    'aplite': (144, 168),
    'basalt': (144, 168),
    'chalk': (180, 180),
    'diorite': (144, 168),
    'emery': (200, 228),
}


def init_app(app):
    global parent_app
    parent_app = app


def _jsonify_common(app: App, target_hw: str) -> dict:
    release = app.releases[-1] if len(app.releases) > 0 else None
    assets = asset_fallback(app.asset_collections, target_hw)

    result = {
        'author': app.developer.name,
        'category_id': app.category_id,
        'category': app.category.name,
        'category_color': app.category.colour,
        'compatibility': {
            'ios': {
                'supported': 'ios' in app.companions or 'android' not in app.companions,
                'min_js_version': 1,
            },
            'android': {
                'supported': 'android' in app.companions or 'ios' not in app.companions,
            },
            **{
                x: {
                    'supported': x in (release.compatibility if release and release.compatibility else ['aplite', 'basalt', 'diorite', 'emery']),
                    'firmware': {'major': 3}
                } for x in ['aplite', 'basalt', 'chalk', 'diorite', 'emery']
            },
        },
        'description': assets.description,
        'developer_id': app.developer_id,
        'hearts': app.hearts,
        'id': app.id,
        'screenshot_hardware': assets.platform,
        'screenshot_images': [{
            'x'.join(str(y) for y in plat_dimensions[target_hw]): generate_image_url(x, *plat_dimensions[target_hw], True)
        } for x in assets.screenshots],
        'source': app.source,
        'title': app.title,
        'type': app.type,
        'uuid': app.app_uuid,
        'website': app.website,
        'capabilities': release.capabilities if release else None,
    }
    return result


def jsonify_app(app: App, target_hw: str) -> dict:
    release = app.releases[-1] if len(app.releases) > 0 else None
    assets = asset_fallback(app.asset_collections, target_hw)

    result = _jsonify_common(app, target_hw)

    result = {
        **result,
        'changelog': [{
            'version': x.version,
            'published_date': x.published_date,
            'release_notes': x.release_notes,
        } for x in app.releases],
        'companions': {
            'ios': jsonify_companion(app.companions.get('ios')),
            'android': jsonify_companion(app.companions.get('android')),
        },
        'created_at': app.created_at,
        'header_images': [{
            '720x320': generate_image_url(x, 720, 320),
            'orig': generate_image_url(x),
        } for x in assets.headers] if len(assets.headers) > 0 else '',
        'links': {
            'add_heart': url_for('legacy_api.add_heart', app_id=app.id, _external=True),
            'remove_heart': url_for('legacy_api.remove_heart', app_id=app.id, _external=True),
            'share': f"{config['APPSTORE_ROOT']}/application/{app.id}",
            'add': 'https://a',
            'remove': 'https://b',
            'add_flag': 'https://c',
            'remove_flag': 'https://d',
        },
        'list_image': {
            '80x80': generate_image_url(app.icon_large, 80, 80, True),
            '144x144': generate_image_url(app.icon_large, 144, 144, True),
        },
        'icon_image': {
            '28x28': generate_image_url(app.icon_small, 28, 28, True),
            '48x48': generate_image_url(app.icon_small, 48, 48, True),
        },
        'published_date': app.published_date,
    }
    if release:
        result['latest_release'] = {
            'id': release.id,
            'js_md5': release.js_md5,
            'js_version': -1,
            'pbw_file': generate_pbw_url(release.id),
            'published_date': release.published_date,
            'release_notes': release.release_notes,
            'version': release.version,
        }
    return result


def algolia_app(app: App) -> dict:
    assets = asset_fallback(app.asset_collections, 'aplite')
    release = app.releases[-1] if len(app.releases) > 0 else None

    tags = [app.type]
    if release:
        tags.extend(release.compatibility or [])
    else:
        tags.extend(['aplite', 'basalt', 'chalk', 'diorite', 'emery'])
        tags.append('companion-app')
    if len(app.companions) == 0:
        tags.extend(['android', 'ios'])
    else:
        tags.extend(app.companions.keys())

    return {
        **_jsonify_common(app, 'aplite'),
        'asset_collections': [{
            'description': x.description,
            'hardware_platform': x.platform,
            'screenshots': [
                generate_image_url(y, *plat_dimensions[x.platform], True) for y in x.screenshots
            ],
        } for x in app.asset_collections.values()],
        'collections': [x.name for x in app.collections],
        'companions': (str(int('ios' in app.companions)) + str(int('android' in app.companions))),
        **({'ios_companion_url': app.companions['ios'].url} if 'ios' in app.companions else {}),
        **({'android_companion_url': app.companions['android'].url} if 'android' in app.companions else {}),
        'icon_image': generate_image_url(app.icon_small, 48, 48, True),
        'list_image': generate_image_url(app.icon_large, 144, 144, True),
        'js_versions': ['-1', '-1', '-1'],
        'objectID': app.id,
        'screenshot_images': [
            generate_image_url(x, 144, 168, True) for x in assets.screenshots
        ],
        '_tags': tags,
    }


def asset_fallback(collections: Dict[str, AssetCollection], target_hw='basalt') -> AssetCollection:
    # These declare the order we want to try getting a collection in.
    # Note that it is not necessarily the case that we will end up with something that
    # could run on the target device - the aim is to produce some assets at any cost,
    # and given that, produce the sanest possible result.
    # In particular, monochrome devices have colour fallbacks to reduce the chance of
    # ending up with round screenshots.
    fallbacks = {
        'aplite': ['aplite', 'diorite', 'basalt'],
        'basalt': ['basalt', 'aplite'],
        'chalk': ['chalk', 'basalt'],
        'diorite': ['diorite', 'aplite', 'basalt'],
        'emery': ['emery', 'basalt', 'diorite', 'aplite']
    }
    fallback = fallbacks[target_hw]
    for hw in fallback:
        if hw in collections:
            return collections[hw]
    return next(iter(collections.values()))


def generate_image_url(img, width=None, height=None, force=False):
    if img is None:
        return None
    if img == '':
        return ''
    url = parent_app.config['IMAGE_ROOT']
    if width is not None or height is not None:
        if not force:
            url += '/fit-in'
        url += f"/{width or ''}x{height or ''}/filters:upscale()"
    url += f"/{img}"
    return url


def generate_pbw_url(release_id: str) -> str:
    return f'{parent_app.config["PBW_ROOT"]}/{release_id}.pbw'


def jsonify_companion(companion: Optional[CompanionApp]) -> Optional[dict]:
    if companion is None:
        return None
    return {
        'id': companion.id,
        'icon': generate_image_url(companion.icon),
        'name': companion.name,
        'url': companion.url,
        'required': True,
        'pebblekit_version': '3' if companion.pebblekit3 else '2',
    }


def get_access_token():
    access_token = request.args.get('access_token')
    if not access_token:
        header = request.headers.get('Authorization')
        if header:
            auth = header.split(' ')
            if len(auth) == 2 and auth[0] == 'Bearer':
                access_token = auth[1]
    if not access_token:
        abort(401)
    return access_token


def authed_request(method, url, **kwargs):
    headers = kwargs.setdefault('headers', {})
    headers['Authorization'] = f'Bearer {get_access_token()}'
    return requests.request(method, url, **kwargs)


def get_uid():
    result = authed_request('GET', f"{config['REBBLE_AUTH_URL']}/api/v1/me?flag_authed=true")
    if result.status_code != 200:
        abort(401)
    return result.json()['uid']