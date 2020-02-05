import posix_ipc
from struct import Struct
from hybrid_lock import HybridLock, CONNECT_TO_EXISTING, CREATE_NEW_OVERWRITE
from speedysvc.client_server.shared_memory.shared_params import get_mmap


class SHMBase:
    # Encoder for command requests
    # length of command [0-255],
    # length of arguments [0~4GB]
    request_serialiser = Struct('!HI')

    # Encoder for the command responses
    # status of response [b'+' is success, b'-' is exception occurred],
    # length of response [0-4GB]
    response_serialiser = Struct('!cI')

    def create_pid_mmap(self, min_size, port, pid, qid):
        # Make it so that the size is always within a power of 2
        # so as to prevent needing to keep reallocating
        # (hopefully an ok balance between too little and too much)
        #
        # The alternatives like just raising an error, or having multipart
        # mode seemed too limiting and too complicated/high overhead
        # for it to be worthwhile.

        socket_name = f'service_{port}_{pid}_{qid}'.encode('ascii')
        return get_mmap(
            socket_name, create=True, new_size=int(min_size*1.5)
        )

    def connect_to_pid_mmap(self, port, pid, qid):
        # Connect to an existing shared mmap
        # Same as above, but don't use in "create" mode as we're
        # connecting to a semaphore/shared memory that
        # (should've been) already created.
        socket_name = f'service_{port}_{pid}_{qid}'.encode('ascii')
        return get_mmap(socket_name, create=False)

    def unlink_pid_mmap(self, port, pid, qid):
        socket_name = f'service_{port}_{pid}_{qid}'.encode('ascii')
        try:
            posix_ipc.unlink_shared_memory(socket_name)
        except:
            pass

    def get_pid_semaphores(self, port, pid, qid, mode):
        assert mode in (CREATE_NEW_OVERWRITE, CONNECT_TO_EXISTING)
        #print("get_pid_semaphores:", port, pid, mode)
        #if mode == CREATE_NEW_OVERWRITE:
        #    print("OVERWRITING:", port, pid)

        client_lock = HybridLock(
            f'client_{port}_pid_{pid}_{qid}'.encode('ascii'), mode,
            initial_value=1
        )
        server_lock = HybridLock(
            f'server_{port}_pid_{pid}_{qid}'.encode('ascii'), mode,
            initial_value=0
        )
        return client_lock, server_lock
