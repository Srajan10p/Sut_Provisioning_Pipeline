import re
import logging
import argparse
import socket
import time
import traceback
import os
import json
import fabric
import paramiko
import six
import base64

if six.PY2:
    from pathlib import Path
if six.PY3:
    from pathlib2 import Path
from datetime import datetime
from invoke.exceptions import CommandTimedOut
from numbers import Number
from paramiko.ssh_exception import NoValidConnectionsError, SSHException
from xml.etree import ElementTree


class SshSutOsProvider():

    DIR_MANIP_TIMEOUT = 1.0
    NET_TIMEOUT_COMP = 3.0
    ASYNC_TRIGGER_TIMEOUT = 0.5

    _PYTEST_HOOK = None

    def __init__(self, ip, user, password, port, retry_cnt, github_token, setup_files_collection, github_clone_repo_url):
        self._ip = ip
        self._user = user
        self._password = password
        self._port = port
        self._retry_cnt = retry_cnt
        self._github_token = github_token
        self._setup_files_collection = setup_files_collection
        self._github_clone_repo_url = github_clone_repo_url


    def _is_alive(self):
        alive = False

        try:
            target = fabric.Connection(host=self._ip, user=self._user, connect_kwargs={'password': self._password}, port=self._port)
            target.open()
            result = target.run('echo alive', hide=False, warn=True, timeout=15,
                            in_stream=self._PYTEST_HOOK)
            target.close()
            if not result.stdout and not result.stderr:
                print("SUT is alive, but couldn't get any message from it")
                alive = False
            else:
                print("SSH connection successfully established and closed. OS is alive")
                alive = True
        except NoValidConnectionsError:
            print("SUT is alive, but couldn't connect to port 22. SUT may still be booting, or sshd is down")
        except SSHException as e:
            print("Unable to connect to SUT. Message: " + str(e))
        except socket.error as e:
            message = e if six.PY2 else e.strerror  # Paramiko uses TimeoutErrors in Python3
            print("OS is not alive. Got socket error code " + str(e.errno) + ", " + str(message))
        return alive and True
    
    def _execute_cmd(self, cmd, timeout, cwd):
        target = fabric.Connection(host=self._ip, user=self._user, connect_kwargs={'password': self._password}, port=self._port)
        with target.cd(cwd):
            target.open()
            exec_result = target.run(cmd, hide=False, warn=True, timeout=timeout,
                                            in_stream=self._PYTEST_HOOK)  # See comment above for detail
            target.close()

        return exec_result

    def execute(self, cmd, timeout, cwd=None):
        retries = 0
        while retries <= int(self._retry_cnt):
            retries += 1
            if timeout is None or not isinstance(timeout, Number):
                raise ValueError("Timeout must be supplied as a valid numeric value in seconds!")
            timeout = timeout + self.NET_TIMEOUT_COMP  # Compensate for slow SSH connections
            if retries > 1:
                timeout = timeout * 2
            # Set desired working directory
            if cwd is None:
                cwd = "."
            # Execute command with Fabric
            try:
                return self._execute_cmd(cmd, timeout, cwd)
            except CommandTimedOut:
                if retries == self._retry_cnt:
                    print(f"Command {cmd} time out!")
                    exit()
                else:
                    continue
            except Exception as e:
                if retries == self._retry_cnt:
                    print("Command Execution failed! Error: ", str(e))
                    exit()
                else:
                    continue
    
    def create_remote_folder(self, remote_path):
        try:
            target = fabric.Connection(host=self._ip, user=self._user, connect_kwargs={'password': self._password}, port=self._port)
            target.open()
            target.run(f'mkdir -p {remote_path}')
            print("Temporary folder Created")
            target.close()
        except CommandTimedOut:
            print("Command Time out")
        except Exception as e:
            print("Command execution failed! Error: ", str(e))

    def create_git_url(self):
        git_repo_url = self._github_clone_repo_url.split("//")
        git_url = git_repo_url[0] + r"//" + self._github_token + r"@" + git_repo_url[1]
        return git_url
    
    def clone_git_repo(self, remote_path, git_repo_url):
        try:
            target = fabric.Connection(host=self._ip, user=self._user, connect_kwargs={'password': self._password}, port=self._port)
            with target.cd(remote_path):
                target.open()
                target.run(f'git clone {git_repo_url}')
                target.close()
        except CommandTimedOut:
            print("Command Time out")
        except Exception as e:
            print("Command execution failed! Error: ", str(e))


    def copy_file_from_local_to_sut(self, source_path, remote_path, zip_file_name):
            try:
                target = fabric.Connection(host=self._ip, user=self._user, connect_kwargs={'password': self._password}, port=self._port)

                target.open()
                # target.run('sudo cp /path/to/local_file.txt /path/to/remote_file.txt')
                result = target.run('pwd')
                destination_path = result.stdout.strip() + r"/" + remote_path + r"/" + zip_file_name
                destination_path = Path(destination_path).as_posix()
                print("destination path ---------", destination_path)
                target.put(source_path, destination_path)
                print(f"Copying files from {source_path} to {destination_path}")
                target.close()
            except CommandTimedOut:
                print("Command Time out")
            except Exception as e:
                print("Command execution failed! Error: ", str(e))
            
    def unzip_remote_file(self, remote_path):
        try:
            target = fabric.Connection(host=self._ip, user=self._user, connect_kwargs={'password': self._password}, port=self._port)
            target.open()
            with target.cd(remote_path):
                zip_files = target.run(f'ls *.zip').stdout.splitlines()

                if len(zip_files) == 0:
                    print("Error: No zip inside the folder")
                    exit()

                for zip_file in zip_files:
                    print(f"unzipping files")
                    target.run(f'unzip {zip_file}')

            target.close()
        except CommandTimedOut:
            print("Command Time out")
        except Exception as e:
            print("Command execution failed! Error: ", str(e))

    def execute_file(self, remote_path):
        try:
            target = fabric.Connection(host=self._ip, user=self._user, connect_kwargs={'password': self._password}, port=self._port)
            target.open()
            with target.cd(remote_path):
                file_names = self._setup_files_collection.split(',')
                for file_name in file_names:
                    print(f"\n-----------------------Executing {file_name}---------------------\n")
                    target.run(f'chmod +x {file_name} && ./{file_name}')
                    print("\n--------------------File Executed-------------------------\n")
                    time.sleep(5)
            target.close()
        except CommandTimedOut:
            print("Command Time out")
        except Exception as e:
            print("Command execution failed! Error: ", str(e))

    def delete_remote_folder(self, remote_path):
        try:
            target = fabric.Connection(host=self._ip, user=self._user, connect_kwargs={'password': self._password}, port=self._port)
            target.open()
            folder_exists = target.run(f'test -d {remote_path} && echo "true" || echo "false"', hide=True).stdout.strip()

            if folder_exists == 'true':
                target.run(f'rm -rf {remote_path}')
                print('Temporary Folder Deleted')
            else:
                print("Folder doesn't exist")
            target.close()
        except CommandTimedOut:
            print("Command Time out")
        except Exception as e:
            print("Command execution failed! Error: ", str(e))
    
    
if __name__ == "__main__":
    query_parser = argparse.ArgumentParser()

    query_parser.add_argument("--host_ip", help="", default=None)
    query_parser.add_argument("--user", help="", default=None)
    query_parser.add_argument("--password", help="", default=None)
    query_parser.add_argument("--port", help="", default=None) 
    query_parser.add_argument("--retry_cnt", help="", default=10) 
    query_parser.add_argument("--github_token", help="", default=None)
    query_parser.add_argument("--setup_files_collection", help="", default=None)
    query_parser.add_argument("--github_clone_repo_url", help="", default=None)
    
    query = query_parser.parse_args()

    host_ip = query.host_ip
    user = query.user
    paswd = query.password
    port = query.port
    retry_cnt = query.retry_cnt
    git_token = query.github_token
    setup_files_collection = query.setup_files_collection
    github_clone_repo_url = query.github_clone_repo_url

    OS_Provider_obj = SshSutOsProvider(host_ip, user, paswd, port, retry_cnt, git_token, setup_files_collection, github_clone_repo_url)
    
    remote_path = r"Desktop/tempr_PnP"

    OS_Provider_obj.delete_remote_folder(remote_path)
    OS_Provider_obj.create_remote_folder(remote_path)
    git_repo_url = OS_Provider_obj.create_git_url()
    OS_Provider_obj.clone_git_repo(remote_path, git_repo_url)

    # OS_Provider_obj.copy_file_from_local_to_sut(source_path, remote_path, zip_file_name)

    # OS_Provider_obj.unzip_remote_file(remote_path)
    
    
    new_remote_path = remote_path + r"/applications.validation.platforms.power-and-performance.server.base-workloads/setup"

    OS_Provider_obj.execute_file(new_remote_path)

    OS_Provider_obj.delete_remote_folder(remote_path)




            