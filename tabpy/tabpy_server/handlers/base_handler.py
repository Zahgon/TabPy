import base64
import binascii
import concurrent
import json
import logging
import tornado.web
from tabpy.tabpy_server.app.app_parameters import SettingsParameters
from tabpy.tabpy_server.handlers.util import hash_password
from tabpy.tabpy_server.handlers.util import AuthErrorStates
import uuid


STAGING_THREAD = concurrent.futures.ThreadPoolExecutor(max_workers=3)


class ContextLoggerWrapper:
    """
    This class appends request context to logged messages.
    """

    @staticmethod
    def _generate_call_id():
        pass

    def __init__(self, request: tornado.httputil.HTTPServerRequest):
        self.call_id = self._generate_call_id()
        self.set_request(request)

        self.tabpy_username = None
        self.log_request_context = False
        self.request_context_logged = False

    def set_request(self, request: tornado.httputil.HTTPServerRequest):
        """
        Set HTTP(S) request for logger. Headers will be used to
        append request data as client information, Tableau user name, etc.
        """
        pass

    def set_tabpy_username(self, tabpy_username: str):
        pass

    def enable_context_logging(self, enable: bool):
        """
        Enable/disable request context information logging.

        Parameters
        ----------
        enable: bool
            If True request context information will be logged and
            every log entry for a request handler will have call ID
            with it.
        """
        pass

    def _log_context_info(self):
        if not self.log_request_context:
            return

        context = f"Call ID: {self.call_id}"

        if self.remote_ip is not None:
            context += f", Caller: {self.remote_ip}"

        if self.method is not None:
            context += f", Method: {self.method}"

        if self.url is not None:
            context += f", URL: {self.url}"

        if self.client is not None:
            context += f", Client: {self.client}"

        if self.tableau_username is not None:
            context += f", Tableau user: {self.tableau_username}"

        if self.tabpy_username is not None:
            context += f", TabPy user: {self.tabpy_username}"

        logging.getLogger(__name__).log(logging.INFO, context)
        self.request_context_logged = True

    def log(self, level: int, msg: str):
        """
        Log message with or without call ID. If call context is logged and
        call ID added to any log entry is specified by if context logging
        is enabled (see CallContext.enable_context_logging for more details).

        Parameters
        ----------
        level: int
            Log level: logging.CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET.

        msg: str
            Message format string.

        args
            Same as args in Logger.debug().

        kwargs
            Same as kwargs in Logger.debug().
        """
        extended_msg = msg
        if self.log_request_context:
            if not self.request_context_logged:
                self._log_context_info()

            extended_msg += f", <<call ID: {self.call_id}>>"

        logging.getLogger(__name__).log(level, extended_msg)


class BaseHandler(tornado.web.RequestHandler):
    def initialize(self, app):
        pass

    def error_out(self, code, log_message, info=None):
        self.set_status(code)
        self.write(json.dumps({"message": log_message, "info": info or {}}))

        self.logger.log(
            logging.ERROR,
            'Responding with status={}, message="{}", info="{}"'.format(
                code, log_message, info
            ),
        )

    def options(self):
        # add CORS headers if TabPy has a cors_origin specified
        self._add_CORS_header()
        self.write({})

    def _add_CORS_header(self):
        """
        Add CORS header if the TabPy has attribute _cors_origin
        and _cors_origin is not an empty string.
        """
        origin = self.tabpy_state.get_access_control_allow_origin()
        if len(origin) > 0:
            self.set_header("Access-Control-Allow-Origin", origin)
            self.logger.log(logging.DEBUG, f"Access-Control-Allow-Origin:{origin}")

        headers = self.tabpy_state.get_access_control_allow_headers()
        if len(headers) > 0:
            self.set_header("Access-Control-Allow-Headers", headers)
            self.logger.log(logging.DEBUG, f"Access-Control-Allow-Headers:{headers}")

        methods = self.tabpy_state.get_access_control_allow_methods()
        if len(methods) > 0:
            self.set_header("Access-Control-Allow-Methods", methods)
            self.logger.log(logging.DEBUG, f"Access-Control-Allow-Methods:{methods}")

    def _get_auth_method(self, api_version) -> (bool, str):
        """
        Finds authentication method if provided.

        Parameters
        ----------
        api_version : str
            API version for authentication.

        Returns
        -------
        bool
            True if known authentication method is found.
            False otherwise.

        str
            Name of authentication method used by client.
            If empty no authentication required.

        (True, '') as result of this function means authentication
        is not needed.
        """
        pass

    def _get_basic_auth_credentials(self) -> bool:
        """
        Find credentials for basic access authentication method. Credentials if
        found stored in Credentials.username and Credentials.password.

        Returns
        -------
        bool
            True if valid credentials were found.
            False otherwise.
        """
        pass

    def _get_credentials(self, method) -> bool:
        """
        Find credentials for specified authentication method. Credentials if
        found stored in self.username and self.password.

        Parameters
        ----------
        method: str
            Authentication method name.

        Returns
        -------
        bool
            True if valid credentials were found.
            False otherwise.
        """
        pass

    def _validate_basic_auth_credentials(self) -> bool:
        """
        Validates username:pwd if they are the same as
        stored credentials.

        Returns
        -------
        bool
            True if credentials has key login and
            credentials[login] equal SHA3(pwd), False
            otherwise.
        """
        pass

    def _validate_credentials(self, method) -> bool:
        """
        Validates credentials according to specified methods if they
        are what expected.

        Parameters
        ----------
        method: str
            Authentication method name.

        Returns
        -------
        bool
            True if credentials are valid.
            False otherwise.
        """
        pass

    def handle_authentication(self, api_version):
        """
        If authentication feature is configured checks provided
        credentials.

        Parameters
        ----------
        api_version : str
            API version for authentication.

        Returns
        -------
        String
            None if authentication is not required and username and password are None.
            None if authentication is required and valid credentials provided.
            NotAuthorized if authenication is required and credentials are incorrect.
            NotRequired if authentication is not required but credentials are provided.
        """
        pass

    def should_fail_with_auth_error(self):
        """
        Checks if authentication is required:
        - if it is not returns false, None
        - if it is required validates provided credentials

        Returns
        -------
        bool
            False if authentication is not required and username
            and password is None or isrequired and validation
            for credentials passes.
            True if validation for credentials failed or
            if authentication is not required and username and password
            fields are not empty.
        """
        return self.auth_error

    def fail_with_auth_error(self):
        """
        Prepares server 401 response and server 406 response depending
        on the value of the self.auth_error flag
        """
        if self.auth_error == AuthErrorStates.NotAuthorized:
            self.logger.log(logging.ERROR, "Failing with 401 for unauthorized request")
            self.set_status(401)
            self.set_header("WWW-Authenticate", f'Basic realm="{self.tabpy_state.name}"')
            self.error_out(
                401,
                info="Unauthorized request.",
                log_message="Invalid credentials provided.",
            )
        else:
            self.logger.log(logging.ERROR, "Failing with 406 for Not Acceptable")
            self.set_status(406)
            self.set_header("WWW-Authenticate", f'Basic realm="{self.tabpy_state.name}"')
            self.error_out(
                406,
                info="Not Acceptable",
                log_message="Username or password provided when authentication not available.",
            )

    def request_body_size_within_limit(self):
        """
        Determines if the request body size is within the specified limit.
        
        Returns
        -------
        bool
            True if the request body size is within the limit, False otherwise.
        """
        if self.max_request_size is not None:
            if "Content-Length" in self.request.headers:
                content_length = int(self.request.headers["Content-Length"])
                if content_length > self.max_request_size:
                    self.error_out(
                        413,
                        info="Request Entity Too Large",
                        log_message=f"Request with size {content_length} exceeded limit of {self.max_request_size} (bytes).",
                    )
                    return False

        return True
