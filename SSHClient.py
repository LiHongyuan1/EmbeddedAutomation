# coding=utf-8
"""
Module providing host manipulation over SSH connection.
:author: Li Hongyuan
:version: 0.1
"""
import paramiko
import logging
from scp import SCPClient

logger = logging.getLogger(__name__)

class SSHClient(object):
    """
    Class providing high-level representation of SSH connection with remote host.
    """
    host = None
    port = None
    user = None
    password = None

    ssh_client = None
    scp_client = None

    def __init__(self, host, port=22, user='root', password='root'):
        """
        Creates a SSHClient.
        :param host: the server to connect to
        :param port: the server port to connect to
        :param user: the username to authenticate as
        :param password: used fot password authentication
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password

        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.load_system_host_keys()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client.connect(host, port, user, password)

        self.scp_client = SCPClient(self.ssh_client.get_transport())

        self.__log('Connection with %s host on %s port has been successfully established...' % (host, str(port)))

    def __del__(self):
        """
        Manages proper instance removal.
        """
        try:
            self.ssh_client.close()
            self.scp_client.close()

            self.__log('Connection with %s host has been closed...' % self.host)
        except Exception as exception:
            self.__log(str(exception))

    def __log(self, data):
        """
        Provides logging functionality.
        :param data: Data to be logged.
        """
        logger.info("Log source: %s" % self.__class__.__name__)
        logger.info(data)

    def get(self, remote_path, local_path='.', recursive=False):
        """
        Transfers files from remote host to the local one.
        :param remote_path: path to retrieve from remote host. Since this is evaluated by scp on the remote host, shell
            wildcards and environment variables may be used.
        :param local_path: path in which to receive files locally
        :param recursive: transfer files and directories recursively
        """
        self.scp_client.get(remote_path, local_path, recursive)

    def put(self, local_paths, remote_path, recursive=False):
        """
        Transfers files to remote host.
        :param local_paths: A single path, or a list of paths to be transferred. Recursive must be True to transfer
            directories
        :param remote_path: A path in which to receive the files on the remote host. Defaults to '.'
        :param recursive: transfer files and directories recursively
        """
        self.scp_client.put(local_paths, remote_path, recursive)

    def execute(self, command, timeout):
        """
        Executes a command on the remote server.
        :param command: the command
        :param timeout: command's channel timeout
        :return: the stdin, stdout and stderr of executed command as 3-tuple
        """
        return self.ssh_client.exec_command(command=command, timeout=timeout)
