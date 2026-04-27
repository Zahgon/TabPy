import base64
import secrets

from pyarrow.flight import ServerMiddlewareFactory, ServerMiddleware
from pyarrow.flight import FlightUnauthenticatedError

from tabpy.tabpy_server.handlers.util import hash_password

class BasicAuthServerMiddleware(ServerMiddleware):
    def __init__(self, token):
        self.token = token

    def sending_headers(self):
        pass

class BasicAuthServerMiddlewareFactory(ServerMiddlewareFactory):
    def __init__(self, creds):
        self.creds = creds
        self.tokens = {}

    def is_valid_user(self, username, password):
        pass

    def start_call(self, info, headers):
        pass
