from os import getpid
from toolkit.patterns.Singleton import Singleton
from hybrid_lock import CREATE_NEW_OVERWRITE
from network_tools.serialisation.RawSerialisation import RawSerialisation
from network_tools.rpc.shared_memory.SHMBase import SHMBase
from network_tools.rpc.shared_memory.shared_params import \
    PENDING, INVALID, SERVER, CLIENT
from network_tools.rpc.shared_memory.JSONMMapArray import JSONMMapArray
from network_tools.rpc.base_classes.ClientProviderBase import ClientProviderBase


class SHMClient(ClientProviderBase, SHMBase, Singleton):
    def __init__(self, server_methods, port=None):
        # Create the shared mmap space/client+server semaphores.

        # Connect to a shared shm/semaphore which stores the
        # current processes which are associated with this service,
        # and add this process' PID.
        ClientProviderBase.__init__(self, server_methods, port)

        self.mmap = self.create_pid_mmap(
            2048, port, getpid()
        )
        self.client_lock, self.server_lock = self.get_pid_semaphores(
            port, getpid(), CREATE_NEW_OVERWRITE
        )

        # Make myself known to the server (my PID)
        # TODO: Figure out what to do in the case
        #  of the PID already being in the array! ====================================================================
        self.pids_array = pids_array = JSONMMapArray(
            self.port, create=False
        )
        with pids_array:
            pids_array.append(getpid())

    def get_server_methods(self):
        return self.server_methods

    def send(self, cmd, args, timeout=-1):
        if isinstance(cmd, bytes):
            # cmd -> a bytes object, most likely heartbeat or shutdown
            serialiser = RawSerialisation
        else:
            # cmd -> a function in the ServerMethods subclass
            serialiser = cmd.serialiser
            cmd = cmd.__name__.encode('ascii')

        # Encode the request command/arguments
        # (I've put the encoding/decoding outside the critical area,
        #  so as to potentially allow for more remote commands from
        #  different threads)
        mmap = self.mmap
        args = serialiser.dumps(args)
        encoded_request = self.request_serialiser.pack(
            len(cmd), len(args)
        ) + cmd + args

        self.client_lock.lock(timeout=timeout)
        try:
            # Send the result to the server!
            if len(encoded_request) > len(self.mmap) - 1:
                mmap[0] = INVALID
                mmap = self.mmap = self.create_pid_mmap(
                    len(encoded_request) + 1, self.port, getpid()
                )
            mmap[1:1+len(encoded_request)] = encoded_request

            # Wait for the server to begin processing
            mmap[0] = PENDING
            #print("BEFORE SERVER UNLOCK:", self.server_lock.get_value(), self.client_lock.get_value())
            self.server_lock.unlock()
            while mmap[0] == PENDING:
                pass # spin! - should check to make sure this isn't being called too often!!! ==========================

            self.server_lock.lock(timeout=-1)  # CHECK ME!!!!
            try:
                # Make sure response state ok,
                # reconnecting to mmap if resized
                if mmap[0] == CLIENT:
                    pass # OK
                elif mmap[0] == INVALID:
                    mmap = self.connect_to_pid_mmap(self.port, getpid())
                    if mmap[0] == CLIENT:
                        pass # OK
                    else:
                        raise Exception("Should never get here!")
                elif mmap[0] == SERVER:
                    raise Exception("Should never get here!")
                else:
                    raise Exception("Unknown state: %s" % mmap[0])

                # Decode the result!
                response_status, data_size = self.response_serialiser.unpack(
                    mmap[1:1+self.response_serialiser.size]
                )
                response_data = mmap[
                    1+self.response_serialiser.size:
                    1+self.response_serialiser.size+data_size
                ]
            finally:
                pass
                #self.server_lock.unlock()
        finally:
            self.client_lock.unlock()

        if response_status == b'+':
            return serialiser.loads(response_data)
        elif response_status == b'-':
            raise Exception(response_data)
        else:
            raise Exception("Unknown status response %s" % response_status)
