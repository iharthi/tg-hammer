import os

from copy import copy
from StringIO import StringIO

from fabric import colors
from fabric.api import abort, env, get, put, require, sudo


DAEMON_TYPES = {
    'systemd': {
        'daemon_cmd': 'systemctl %(action)s %(name)s',
        'target_dir': '/etc/systemd/system',
        'file_extension': 'service',
    },
    'supervisor': {
        'daemon_cmd': 'supervisorctl %(action)s %(name)s',
        'target_dir': '/etc/supervisord/conf.d/',
        'file_extension': 'conf',
    },
    'upstart': {
        'daemon_cmd': 'service %(name)s %(action)s',
        'target_dir': '/etc/init',
        'file_extension': 'conf',
    },
}


def get_service_daemon():
    require('service_daemon')

    if env.service_daemon not in DAEMON_TYPES:
        abort('Provided `service_daemon` %s is invalid. Supported daemon types are: %s' % (env.service_daemon, ', '.join(DAEMON_TYPES)))

    daemon_conf = copy(DAEMON_TYPES[env.service_daemon])

    # Support loading target_dir from env
    daemon_conf['target_dir'] = getattr(env, 'service_daemon_target_dir', daemon_conf['target_dir'])

    if not daemon_conf['target_dir']:
        abort('`env.service_daemon_target_dir` must not be empty')

    return env.service_daemon, daemon_conf


def install_services(services):
    """Install provided services by uploading configuration files to the detected ``daemon_type`` specific directory

    :param services: List of services to install where each item is a tuple with the signature: ``(target_name, file_data)``

    **Note:**
        One can overwrite the default target dir via ``env.service_daemon_target_dir``

    **Warning:**
        For supervisor the default include dir is `/etc/supervisord/conf.d/`, this directory must be included
        in the global supervisor configuration.
    """

    daemon_type, daemon_conf = get_service_daemon()

    for target_name, file_data in services:
        target_path = os.path.join(daemon_conf['target_dir'], '%s.%s' % (target_name, daemon_conf['file_extension']))

        put(local_path=StringIO(file_data), remote_path=target_path, use_sudo=True)

    if daemon_type == 'supervisor':
        # Ensure configuration files are reloaded
        manage_service('supervisorctl', 'reread')
        manage_service('supervisorctl', 'update')

    elif daemon_type == 'systemd':
        # Ensure configuration files are reloaded
        manage_service('systemctl', 'daemon-reload')

        # Ensure services are started on startup
        manage_service([target_name for target_name, file_data in services], 'enable')


def install_services_cp(services):
    """Install provided services by copying the remote file to the detected ``daemon_type`` specific directory

    :param services: List of services to install where each item is a tuple with the signature: ``(target_name, remote_file_path)``

    The remote_file_path supports the following keywords:

    -  ``${DAEMON_TYPE}``: Replaced with the detected daemon type (see `DAEMON_TYPES`)
    -  ``${DAEMON_FILE_EXTENSION}``: Replaced with the `file_extension` value for the detected daemon type (see `DAEMON_TYPES`)

    **Note:**
        One can overwrite the default target dir via ``env.service_daemon_target_dir``

    **Warning:**
        For supervisor the default include dir is `/etc/supervisord/conf.d/`, this directory must be included
        in the global supervisor configuration.
    """

    prepared_services = []
    daemon_type, daemon_conf = get_service_daemon()

    for target_name, remote_file_path in services:
        # Construct remote path
        remote_file_path = remote_file_path.replace('${DAEMON_TYPE}', daemon_type)
        remote_file_path = remote_file_path.replace('${DAEMON_FILE_EXTENSION}', daemon_conf['file_extension'])

        # Download the remote file
        buf = StringIO()
        get(remote_file_path, buf)

        # store it in prepared services
        prepared_services.append(
            (target_name, buf.getvalue()),
        )

    # Use standard install_services to install them
    return install_services(prepared_services)


def manage_service(names, action):
    """Perform `action` on services

    :param names: Can be a list of services or a name of a single service to control
    :param action: Action that should be executed for the given services
    """
    if not isinstance(names, (list, tuple)):
        names = [names, ]

    daemon_type, daemon_conf = get_service_daemon()

    for name in names:
        full_cmd = daemon_conf['daemon_cmd'] % {
            'name': name,
            'action': action,
        }

        try:
            sudo(full_cmd, warn_only=True)

        except Exception as e:
            print(colors.red('Failed: %s', full_cmd))
            print(e)
            print('')