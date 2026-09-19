"""Explicitly owned forum database observation and reset helpers."""
import json
import subprocess

NAME = 'curation-webarena-biography-v1'
ORIGIN = 'http://localhost:19099'
USER = 'MarvelsGrantMan136'
IMAGE = 'am1n3e/webarena-verified-reddit@sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46'


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def inspect():
    data = json.loads(command('docker', 'inspect', NAME))[0]
    assert data['Config']['Labels'].get('intent.owner') == 'curation-biography'
    assert not data['Mounts']
    for container_port, host_port in [('80/tcp', '19099'), ('8877/tcp', '19098')]:
        assert data['HostConfig']['PortBindings'][container_port] == [{'HostIp': '127.0.0.1', 'HostPort': host_port}]
    return {key: data[key] for key in ['Id', 'Image', 'Created', 'Mounts']}


def sql(query):
    inspect()
    return command('docker', 'exec', '--user', 'postgres', NAME, 'psql', '-v', 'ON_ERROR_STOP=1', '-d', 'postmill', '-Atc', query)


def rows(query):
    return [json.loads(line) for line in sql('SELECT row_to_json(q) FROM (' + query + ')q').splitlines() if line]


def initial_ids():
    return [int(value) for value in sql('SELECT id FROM submissions ORDER BY id').splitlines()]


def posts_new(baseline):
    assert isinstance(baseline, list) and all(type(value) is int for value in baseline)
    ids = sorted(set(initial_ids()) - set(baseline))
    if not ids:
        return []
    chosen = ','.join(str(value) for value in ids)
    return rows('SELECT s.id,s.forum_id,f.name AS forum_name,s.user_id,u.username,s.title,s.body,s.url,s.timestamp,s.edited_at,s.visibility,s.moderated '
                'FROM submissions s JOIN forums f ON f.id=s.forum_id JOIN users u ON u.id=s.user_id '
                f'WHERE s.id IN ({chosen}) ORDER BY s.id')


def cleanup_created(baseline):
    created = posts_new(baseline)
    assert all(row['username'] == USER for row in created), 'Unexpected writer in owned instance'
    if not created:
        return
    ids = ','.join(str(row['id']) for row in created)
    assert sql(f'SELECT count(*) FROM comments WHERE submission_id IN ({ids})') == '0'
    assert sql(f'SELECT count(*) FROM notifications WHERE submission_id IN ({ids})') == '0'
    sql(f'BEGIN; DELETE FROM submission_votes WHERE submission_id IN ({ids}); '
        f'DELETE FROM submissions_flairs WHERE submission_id IN ({ids}); '
        f'DELETE FROM submissions WHERE id IN ({ids}); COMMIT;')
    assert posts_new(baseline) == []
