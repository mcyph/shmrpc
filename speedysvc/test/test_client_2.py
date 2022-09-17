from TestServiceClient import TestServiceClient


if __name__ == '__main__':
    from time import time
    t = time()
    client = TestServiceClient()
    for i in range(1000000):
        assert client.test_raw_echo(b'blah') == b'blah'
    print(time()-t)

    t = time()
    for i in client.test_json_echo_iterator('blah'):
        assert i == 'blah'
    print(time() - t)