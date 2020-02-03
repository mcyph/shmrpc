import os
import sys
import json
import time
import signal
import _thread
import importlib
import subprocess
from sys import argv
from multiprocessing import cpu_count

from shmrpc.logger.std_logging.LoggerServer import LoggerServer
from shmrpc.logger.std_logging.FIFOJSONLog import FIFOJSONLog
from shmrpc.toolkit.io.make_dirs import make_dirs
from shmrpc.toolkit.py_ini.read.ReadIni import ReadIni
from shmrpc.kill_pid_and_children import kill_pid_and_children
from shmrpc.web_monitor.app import web_service_manager, run_server


_handling_sigint = [False]


def signal_handler(sig, frame):
    """
    SIGINT received, likely due to ctrl+c
    try to exit as cleanly as possible,
    recursively exiting child processes
    """
    if _handling_sigint[0]:
        return
    _handling_sigint[0] = True

    waiting_num = [0]

    def wait_to_exit(proc):
        try:
            print("Main service waiting for PID to exit:", proc.pid)
            kill_pid_and_children(proc.pid)
        finally:
            waiting_num[0] -= 1

    for proc in services.DProcByName.values():
        waiting_num[0] += 1
        _thread.start_new_thread(wait_to_exit, (proc,))

    while waiting_num[0]:
        time.sleep(0.01)
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


class Services:
    def __init__(self):
        self.DProcByPort = {}
        self.DProcByName = {}
        self.DLoggerServersByPort = {}
        self.DLoggerServersByName = {}
        self.DValuesByPort = {}
        self.DValuesByName = {}

        self.DValues = ReadIni().read_D(argv[-1])

        self.DArgKeys = {
            'log_dir': lambda x: x,
            'tcp_bind': lambda x: x,
            'tcp_compression': lambda x: x,
            'tcp_allow_insecure_serialisation': self.__convert_bool,
            'max_proc_num': self.__greater_than_0_int,
            'min_proc_num': self.__greater_than_0_int,
            'wait_until_completed': self.__convert_bool
        }

        if 'web monitor' in self.DValues:
            self.DWebMonitor = self.DValues.pop('web monitor')
        else:
            self.DWebMonitor = {}

        if 'defaults' in self.DValues:
            DDefaults = self.DValues.pop('defaults')
            self.DDefaults = DDefaults = {
                k: self.DArgKeys[k](v) for k, v in DDefaults.items()
            }
        else:
            self.DDefaults = DDefaults = {}

        if not 'log_dir' in DDefaults:
            # Note this - the logger parent always uses the "default" dir currently
            DDefaults['log_dir'] = '/tmp/shmrpc_logs'

        # Create the "parent logger" for all processes
        make_dirs(DDefaults['log_dir'])
        self.fifo_json_log_parent = FIFOJSONLog(
            f"{DDefaults['log_dir']}/global_log.json"
        )
        web_service_manager.set_logger_parent(
            self.fifo_json_log_parent
        )

        # Start all services, as defined in the .ini file
        # TODO: Allow starting only some services using the commandline?
        self.start_all_services()

    def __convert_bool(self, i):
        return {
            'true': True,
            'false': False,
            '0': False,
            '1': True
        }[i.lower()]

    def __greater_than_0_int(self, i):
        i = int(i)
        assert i > 0, "Value should be greater than 0"
        return i

    #====================================================================#
    #                          Start Services                            #
    #====================================================================#

    def start_all_services(self):
        """

        :return:
        """
        for service_class_name in self.DValues.keys():
            # Note that DValues is an OrderedDict, which means services
            # are created in the order they're defined in the .ini file.
            self.start_service(service_class_name)

    def start_service_by_port(self, port):
        """

        :param port:
        :return:
        """
        self.start_service(self.DValuesByPort[port])

    def start_service_by_name(self, name):
        """

        :param name:
        :return:
        """
        self.start_service(self.DValuesByName[name])

    def start_service(self, service_class_name):
        """

        :param service_class_name:
        :return:
        """
        # print("SECTION:", section)
        DSection = self.DValues[service_class_name].copy()
        import_from = DSection.pop('import_from')
        server_methods = getattr(
            importlib.import_module(import_from),
            service_class_name
        )
        assert not server_methods.port in self.DProcByPort, \
            f"Service {server_methods.name}:{server_methods.port} has already been started!"
        assert not server_methods.name in self.DProcByName, \
            f"Service {server_methods.name}:{server_methods.port} has already been started!"

        self.DValuesByPort[server_methods.port] = service_class_name
        self.DValuesByName[server_methods.name] = service_class_name

        DArgs = self.DDefaults.copy()
        DArgs.update({k: self.DArgKeys[k](v) for k, v in DSection.items()})
        self.__run_multi_proc_server(
            server_methods, import_from, service_class_name,
            **DArgs,
            fifo_json_log_parent=self.fifo_json_log_parent
        )

    #====================================================================#
    #                           Stop Services                            #
    #====================================================================#

    def stop_service_by_port(self, port):
        """

        :param port:
        :return:
        """
        proc = self.DProcByPort[port]
        self.DLoggerServersByPort[port].stop_collecting()
        self.__kill_proc(proc)
        self.DLoggerServersByPort[port].set_service_status('stopped')

    def stop_service_by_name(self, name):
        """

        :param name:
        :return:
        """
        proc = self.DProcByName[name]
        self.DLoggerServersByName[name].stop_collecting()
        self.__kill_proc(proc)
        self.DLoggerServersByPort[name].set_service_status('stopped')

    def __kill_proc(self, proc):
        self.DProcByPort = {
            port: i_proc for port, i_proc in self.DProcByPort.copy().items()
            if proc != i_proc
        }
        self.DProcByName = {
            name: i_proc for name, i_proc in self.DProcByPort.copy().items()
            if proc != i_proc
        }
        kill_pid_and_children(proc.pid)

    #====================================================================#
    #                            Run Service                             #
    #====================================================================#

    def __run_multi_proc_server(self,
                                server_methods, import_from, section,
                                log_dir='/tmp',
                                tcp_bind=None,
                                tcp_compression=None,
                                tcp_allow_insecure_serialisation=False,

                                max_proc_num=cpu_count(),
                                min_proc_num=1,
                                wait_until_completed=True,

                                fifo_json_log_parent=None):

        print(f"{server_methods.name} parent: starting service")

        # Create the logger server, which allows
        # the services to communicate back with us
        make_dirs(f"{log_dir}/{server_methods.name}")
        if not server_methods.port in self.DLoggerServersByPort:
            # Create a logger server for each service, persistent to this process
            # This makes it so we can restart services
            # While it would be nice to restart the logger too,
            # currently that'd require a fair amount of refactoring
            logger_server = LoggerServer(
                log_dir=f'{log_dir}/{server_methods.name}/',
                server_methods=server_methods,
                fifo_json_log_parent=fifo_json_log_parent
            )
            self.DLoggerServersByName[server_methods.name] = logger_server
            self.DLoggerServersByPort[server_methods.port] = logger_server
        logger_server = self.DLoggerServersByPort[server_methods.port]

        # Assemble relevant parameters
        # TODO: This is redundant - should all be supplied using self.DValues!
        DEnv = os.environ.copy()
        DEnv["PATH"] = "/usr/sbin:/sbin:" + DEnv["PATH"]
        DArgs = {
            'import_from': import_from,
            'section': section,
            'tcp_bind': tcp_bind,
            'tcp_compression': tcp_compression,
            'tcp_allow_insecure_serialisation': tcp_allow_insecure_serialisation,

            'min_proc_num': min_proc_num,
            'max_proc_num': max_proc_num,
            'max_proc_mem_bytes': None,

            'new_proc_cpu_pc': 0.3,
            'new_proc_avg_over_secs': 20,
            'kill_proc_avg_over_secs': 240,

            'wait_until_completed': wait_until_completed
        }
        proc = subprocess.Popen([
            'python3', '-m',
            'shmrpc.service_managers.multi_process_manager.MultiProcessManager',
            json.dumps(DArgs)
        ], env=DEnv)
        self.DProcByName[server_methods.name] = proc
        self.DProcByPort[server_methods.port] = proc

        logger_server.proc = proc  # HACK!
        web_service_manager.add_service(logger_server)

        if wait_until_completed:
            while logger_server.get_service_status() != 'started':
                time.sleep(0.1)


if __name__ == '__main__':
    services = Services()
    web_service_manager.set_services(services)
    print("Services started - starting web monitoring interface")

    # OPEN ISSUE: Allow binding to a specific address here? ====================================
    # For security reasons, it's probably (in almost all cases)
    # better to only allow on localhost, to prevent other people
    # stopping services, etc

    # Note opening the web server from a different thread -
    # this allows intercepting ctrl+c/SIGINT
    # It may be that SIGINT is handled in the actual webserver code,
    # but I want to make sure child processes clean up when SIGINT is called.

    _thread.start_new_thread(run_server, (), {
        'debug': False,
        'host': services.DWebMonitor.get('host', '127.0.0.1'),
        'port': int(services.DWebMonitor.get('port', '5155')),
    })
    while 1:
        time.sleep(10)
