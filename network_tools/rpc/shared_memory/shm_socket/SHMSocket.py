import mmap
import time
import struct
from hybrid_lock import HybridSpinSemaphore, \
    CONNECT_TO_EXISTING, CREATE_NEW_OVERWRITE
import posix_ipc
from network_tools.rpc.shared_memory.shared_params import MSG_SIZE

# Create an int encoder to allow encoding length
# and return client ID
int_struct = struct.Struct('i')

ALL_DATA_RECEIVED = -1
NO_MORE_DATA = -2


class SHMSocket:
    def __init__(self,
                 socket_name, init_resources=False,
                 msg_size=MSG_SIZE, timeout=10):  # 10 seconds timeout
        """
        A single-directional "socket"-like object, which provides
        sequential shared memory-based "pipes", synchronised
        by a hybrid spinlocks/named semaphores.

        This provides extremely high throughput, extremely
        low latency IPC, which should largely be
        limited by the speed of serialisation/deserialisation,
        and the python interpreter.

        Note that after a process which initialised the resources
        has exited abnormally (e.g. due to a segfault), the shared
        memory and semaphore can still exist on the OS.

        :param socket_name:
        :param init_resources:
        :param msg_size:
        :param timeout:
        """

        # NOTE: ntc stands for "nothing to collect"
        # and rtc stands for "ready to collect"
        # having 2 semaphores like this allows for blocking
        # operations between the put/get operations

        self.socket_name = socket_name
        self.init_resources = init_resources
        self.last_used_time = time.time()
        self.timeout = timeout

        rtc_bytes = (socket_name + '_rtc').encode('ascii')
        ntc_bytes = (socket_name + '_ntc').encode('ascii')

        if init_resources:
            # Clean up since last time
            try: posix_ipc.unlink_shared_memory(socket_name)
            except: pass

            # Create the shared memory and the semaphore,
            # and map it with mmap
            self.memory = memory = posix_ipc.SharedMemory(
                socket_name, posix_ipc.O_CREX, size=msg_size
            )
            self.mapfile = mmap.mmap(memory.fd, memory.size)

            # Make it so that the write semaphore is incremented by 1,
            # so we can initially write to the semaphore
            # (but don't increment the read semaphore,
            #  as nothing is in the queue yet!)

            self.rtc_mutex = HybridSpinSemaphore(
                rtc_bytes, CREATE_NEW_OVERWRITE,
                initial_value=0
            )
            self.ntc_mutex = HybridSpinSemaphore(
                ntc_bytes, CREATE_NEW_OVERWRITE,
                initial_value=1
            )

            assert self.rtc_mutex.get_value() == 0, self.rtc_mutex.get_value()
            assert self.ntc_mutex.get_value() == 1, self.ntc_mutex.get_value()
        else:
            # Same as above, but don't use in "create" mode as we're
            # connecting to a semaphore/shared memory that
            # (should've been) already created.
            self.memory = memory = posix_ipc.SharedMemory(socket_name)
            self.mapfile = mmap.mmap(memory.fd, memory.size)

            self.rtc_mutex = HybridSpinSemaphore(
                rtc_bytes, CONNECT_TO_EXISTING,
                initial_value=0
            )
            self.ntc_mutex = HybridSpinSemaphore(
                ntc_bytes, CONNECT_TO_EXISTING,
                initial_value=1
            )

        print("RTC:", self.rtc_mutex.get_value(), "NTC:", self.ntc_mutex.get_value())

        # We (apparently) don't need the file
        # descriptor after it's been memory mapped
        memory.close_fd()

    def log(self, *msgs):
        print(f'{self.socket_name}:', *msgs)

    def __del__(self):
        """
        Clean up
        """
        if hasattr(self, 'mapfile'):
            self.mapfile.close()

        if self.init_resources:
            # Only clear out the memory/
            # mutexes if we created them
            self.memory.unlink()

            self.rtc_mutex.destroy()
            self.ntc_mutex.destroy()
        else:
            # Otherwise just close the mutexes
            del self.rtc_mutex
            del self.ntc_mutex

    def put(self, data: bytes, timeout=None):
        """
        Put an item into the (single-item) queue
        :param data: the data as a string of bytes
        """

        # It would be possible to make it so that there were lots of
        # different memory blocks, and the semaphore initially
        # incremented to the maximum value so as to (potentially)
        # allow for increased throughput.

        # TODO: Support very large queue items!!! ==============================================================

        #print(f"{self.socket_name}: put lock ntc_mutex {self.ntc_mutex.get_value()}")
        self.last_used_time = time.time()
        self.ntc_mutex.lock()

        self.mapfile[0:int_struct.size] = int_struct.pack(len(data))
        self.mapfile[int_struct.size:int_struct.size+len(data)] = data

        # Let the data be read, signalling
        # data is "ready to collect"
        #print(f"{self.socket_name}: put unlock rtc_mutex {self.rtc_mutex.get_value()}")
        self.rtc_mutex.unlock()

    def get(self, timeout=None):
        """
        Get/pop an item from the (single-item) queue
        :return: the item from the queue
        """
        #print(f"{self.socket_name}: get lock rtc_mutex {self.rtc_mutex.get_value()}")
        self.last_used_time = time.time()
        self.rtc_mutex.lock()

        amount = int_struct.unpack(self.mapfile[0:int_struct.size])[0]
        data = self.mapfile[int_struct.size:int_struct.size+amount]

        # Signal there's "nothing to collect"
        # to allow future put operations
        #print(f"{self.socket_name}: get unlock ntc_mutex {self.ntc_mutex.get_value()}")
        self.ntc_mutex.unlock()
        return data

    def get_sockets_destroyed(self):
        """

        :return:
        """
        return self.rtc_mutex.get_destroyed() or \
               self.ntc_mutex.get_destroyed()

    def get_last_used_time(self):
        """

        :return:
        """
        return self.last_used_time


if __name__ == '__main__':
    import time

    server_socket = SHMSocket('q', init_resources=True)
    client_socket = SHMSocket('q')
    DATA = b'my ranadasdmsak data'*20

    from_t = time.time()
    for x in range(1000000):
        server_socket.put(DATA)
        assert client_socket.get() == DATA
    print(time.time()-from_t)