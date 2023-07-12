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
import subprocess
import zipfile
import shutil
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
    ATF_USER = "sys_degsi1"
    ATF_PASSWORD = "zaq1@wsxcde34rfvbgt5"
    Retention_period = 1

    _PYTEST_HOOK = None

    def __init__(self, git_url, org, git_repo, NUC_Host, nuc_host_ip, nuc_user, nuc_password, SUT_Host, sut_host_ip, sut_user, sut_password, atf_url):
        self.git_url = git_url
        self.org = org
        self.git_repo = git_repo

        self.NUC_Host = NUC_Host

        self.nuc_host_ip = nuc_host_ip
        self.nuc_user = nuc_user
        self.nuc_password = nuc_password

        self.SUT_Host = SUT_Host

        self.sut_host_ip = sut_host_ip
        self.sut_user = sut_user
        self.sut_password = sut_password

        self.atf_url = atf_url


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
    
    def zip_and_replace_folder(self, folder_path):
        zip_path = folder_path + '.zip'
        print(zip_path)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, folder_path))

        ssh_commands = [
                f'rmdir /s /q "{folder_path}"',
                'exit'
            ]
        
        for ssh_command in ssh_commands:
                try:
                    subprocess.run(ssh_command, check=True, shell=True)
                except subprocess.CalledProcessError as e:
                    print(f"Error cloning repository: {e}")
                    return
        print("------------------------------   Zip File Created and the Cloned Repo Deleted   ---------------------------------------------")
        
        os.rename(zip_path, folder_path + '.zip')


    def create_local_folder(self, remote_path):
        try:
            subprocess.run(f'mkdir \p {remote_path}')
            print("------------------------------   Git Folder Created   ---------------------------------------------")
        except subprocess.CalledProcessError as e:
            print(f"Error creating folder: {e}")

    def create_git_url(self):
        if self.git_url != None:
            if ".git" in self.git_url:
                return self.git_url
            else:
                local_git_url = self.git_url + r".git"
                return local_git_url
        else:
            local_git_url = r"https://github.com/" + self.org + r"/" + self.git_repo + r".git"
            return local_git_url

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

    def delete_local_folder(self, remote_path):
        ssh_commands = [
                f'rmdir /s /q "{remote_path}"',
                'exit'
            ]
        
        for ssh_command in ssh_commands:
            try:
                subprocess.run(ssh_command, check=True, shell=True)
            except subprocess.CalledProcessError as e:
                print(f"Error deleting folder: {e}")
                return
        print("------------------------------   Git Folder Deleted   ---------------------------------------------")
    

    def git_clone(self, url, destination):
        ssh_commands = [
                f'git clone {url} {destination}',
                'exit'
            ]
        
        for ssh_command in ssh_commands:
                try:
                    subprocess.run(['bash', '-c', ssh_command])
                except subprocess.CalledProcessError as e:
                    print(f"Error cloning repository: {e}")
                    return
        print("------------------------------   Git Repo Cloned   ---------------------------------------------")

    def atf_upload(self):
        if self.atf_url[-1] != '/':
            self.atf_url = f"{self.atf_url}/"
        ssh_commands = [
                f'curl -u {self.ATF_USER}:{self.ATF_PASSWORD} -T "C:/Users/Public/Git_Cloned_repo/{self.git_repo}.zip" "{self.atf_url}{self.git_repo}.zip;retention.days={self.Retention_period}"',
                'exit'
            ]
        
        for ssh_command in ssh_commands:
            try:
                subprocess.run(ssh_command, check=True, shell=True)
            except subprocess.CalledProcessError as e:
                print(f"Error cloning repository: {e}")
                return
        print("------------------------------   Zip Uploaded to Artifactory   ---------------------------------------------")

        return atf_url

    def atf_zip_download(self, Host):

        if (Host == 'Nuc'):
            if self.NUC_Host == 'true':
                Host_IP = self.nuc_host_ip
                Host_User = self.nuc_user
                Host_Password = self.nuc_password
            else:
                return
            
        elif (Host == 'Sut'):
            if self.SUT_Host:
                Host_IP = self.sut_host_ip
                Host_User = self.sut_user
                Host_Password = self.sut_password
            else:
                return 

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(Host_IP, Host_User, Host_Password)
            stdin, stdout, stderr = client.exec_command('uname -s')
            os_type = stdout.read().decode().strip()

            if os_type == 'Linux':
                stdin, stdout, stderr = client.exec_command(f"curl -u {self.ATF_USER}:{self.ATF_PASSWORD} --noproxy '*' -L {self.atf_url}{self.git_repo}.zip --output /home/{self.git_repo}.zip")
                
            else:
                print("Windows")
                stdin, stdout, stderr = client.exec_command('mkdir \p "C:/repo"')
                stdin, stdout, stderr = client.exec_command(f"curl -u {self.ATF_USER}:{self.ATF_PASSWORD} --noproxy '*' -L {self.atf_url}{self.git_repo}.zip --output C:/{self.git_repo}.zip")
            
            print("------------------------------   Zip Downloaded from Artifactory   ---------------------------------------------")
            client.close()
            
        except paramiko.AuthenticationException:
            print('Authentication failed')
        except paramiko.SSHException as e:
            print('SSH connection failed: ' + str(e))
        except paramiko.socket.error as e:
            print('Connection failed: ' + str(e))


if __name__ == "__main__":
    query_parser = argparse.ArgumentParser()


    query_parser.add_argument("--git_url", help="", default=None)
    query_parser.add_argument("--org", help="", default=None)
    query_parser.add_argument("--git_repo", help="", default=None)

    query_parser.add_argument("--NUC_Host", help="", default=False)

    query_parser.add_argument("--nuc_host_ip", help="", default=None)
    query_parser.add_argument("--nuc_user", help="", default="General")
    query_parser.add_argument("--nuc_password", help="", default="Passw0rd")

    query_parser.add_argument("--SUT_Host", help="", default=False)

    query_parser.add_argument("--sut_host_ip", help="", default=None)
    query_parser.add_argument("--sut_user", help="", default="root")
    query_parser.add_argument("--sut_password", help="", default="password")

    query_parser.add_argument("--atf_url", help="", default="https://ubit-artifactory-ba.intel.com/artifactory/dcg-dea-srvplat-repos/Automation_Tools/PAIV_DevOps/SUT_Provisioning/")

    query = query_parser.parse_args()

    git_url = query.git_url
    org = query.org
    git_repo = query.git_repo

    NUC_Host = query.NUC_Host

    nuc_host_ip = query.nuc_host_ip
    nuc_user = query.nuc_user
    nuc_password = query.nuc_password

    SUT_Host = query.SUT_Host

    sut_host_ip = query.sut_host_ip
    sut_user = query.sut_user
    sut_password = query.sut_password

    atf_url = query.atf_url

    if (git_url != None):
        git_repo = git_url.split("/")[-1]

    OS_Provider_obj = SshSutOsProvider(git_url, org, git_repo, NUC_Host, nuc_host_ip, nuc_user, nuc_password, SUT_Host, sut_host_ip, sut_user, sut_password, atf_url)
    url = OS_Provider_obj.create_git_url()
    des = r'C:/Users/Public/Git_Cloned_repo'

    OS_Provider_obj.delete_local_folder(des)
    OS_Provider_obj.create_local_folder(des)

    dest = des + r"/" + git_repo
    
    OS_Provider_obj.git_clone(url, dest)
    OS_Provider_obj.zip_and_replace_folder(dest)
    atf_url = OS_Provider_obj.atf_upload()

    OS_Provider_obj.atf_zip_download('Nuc')
    OS_Provider_obj.atf_zip_download('Sut')

    # OS_Provider_obj.delete_local_folder(des)
  