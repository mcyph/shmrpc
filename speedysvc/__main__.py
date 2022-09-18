import time
import signal
import _thread

from speedysvc.Services import Services, signal_handler
from speedysvc.web_monitor.app import web_service_manager, run_server


if __name__ == '__main__':
    services = Services()
    web_service_manager.set_services(services)
    #services.start_all_services()

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
        'debug': True,
        'host': services.web_monitor_dict.get('host', '127.0.0.1'),
        'port': int(services.web_monitor_dict.get('service_port', '5155')),
    })

    while True:
        try:
            if hasattr(signal, 'pause'):
                signal.pause()
            else:
                time.sleep(60)
        except KeyboardInterrupt:
            signal_handler(None, None)
