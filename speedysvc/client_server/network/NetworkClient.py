import time
import warnings
import socket
from os import getpid
from speedysvc.toolkit.documentation.copydoc import copydoc

from speedysvc.client_server.base_classes.ClientProviderBase import ClientProviderBase
from speedysvc.client_server.network.consts import len_packer, response_packer
from speedysvc.compression.compression_types import snappy_compression


class NetworkClient(ClientProviderBase):
    def __init__(self,
                 server_methods,
                 host='127.0.0.1', port=None,
                 compression_inst=snappy_compression):
        """

        :param server_methods:
        :param host:
        """
        self.host = host
        self.port = port
        ClientProviderBase.__init__(self, server_methods)
        self.compression_inst = compression_inst
        self.__connect()

    def __connect(self):
        self.conn_to_server = conn_to_server = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        )
        conn_to_server.setsockopt(
            socket.SOL_TCP, socket.TCP_NODELAY, 1
        )
        port = (
            self.port
            if self.port is not None
            else self.server_methods.port
        )
        conn_to_server.connect((self.host, port))
        conn_to_server.send(
            self.compression_inst.typecode
        )

    def __del__(self):
        self.conn_to_server.close()

    @copydoc(ClientProviderBase.send)
    def send(self, fn, data):
        actually_compressed, data = \
            self.compression_inst.compress(fn.serialiser.dumps(data))
        cmd = fn.__name__.encode('ascii')
        prefix = len_packer.pack(int(actually_compressed), len(data), len(cmd))

        displayed_reconnect_msg = False
        while True:
            # Try to keep reconnecting if
            # connection no longer functioning
            try:
                self.conn_to_server.send(prefix + cmd + data)
                break
            except socket.error:
                if not displayed_reconnect_msg:
                    displayed_reconnect_msg = True
                    warnings.warn(
                        f"Client [pid {getpid()}]: "
                        f"TCP connection to service "
                        f"{self.server_methods.name} reset - "
                        f"the service may need to be checked/restarted!"
                    )

                import time
                time.sleep(1)
                self.__connect()

        def recv(amount):
            # Note string concatenation is slower in earlier versions
            # of python, but should be faster than list concat in later
            # versions after 3.
            r = b''
            while len(r) != amount:
                r += self.conn_to_server.recv(amount)
            return r

        actually_compressed, data_len, status = \
            response_packer.unpack(recv(response_packer.size))
        data = recv(data_len)
        if actually_compressed:
            data = self.compression_inst.decompress(data)

        if status == b'+':
            return fn.serialiser.loads(data)
        else:
            raise Exception(data.decode('utf-8'))


if __name__ == '__main__':
    inst = NetworkClient(5555)
    t = time.time()
    for x in range(500000):
        i = b"my vfdsfdsfsdfsdfsdfdsfsdaluetasdsadasdsadsadsaest"# bytes([randint(0, 255)])*500
        #print('SEND:', i)
        assert inst.send('echo', i) == i

    print(time.time()-t)
