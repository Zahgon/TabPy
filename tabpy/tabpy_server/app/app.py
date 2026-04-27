import concurrent.futures
import configparser
import logging
import multiprocessing
import os
import shutil
import signal
import ssl
import sys
import _thread

import tornado
from tornado.http1connection import HTTP1Connection

import tabpy
import tabpy.tabpy_server.app.arrow_server as pa
from tabpy.tabpy import __version__
from tabpy.tabpy_server.app.app_parameters import ConfigParameters, SettingsParameters
from tabpy.tabpy_server.app.util import parse_pwd_file
from tabpy.tabpy_server.handlers.basic_auth_server_middleware_factory import BasicAuthServerMiddlewareFactory
from tabpy.tabpy_server.handlers.no_op_auth_handler import NoOpAuthHandler
from tabpy.tabpy_server.management.state import TabPyState
from tabpy.tabpy_server.management.util import _get_state_from_file
from tabpy.tabpy_server.psws.callbacks import init_model_evaluator, init_ps_server
from tabpy.tabpy_server.psws.python_service import PythonService, PythonServiceHandler
from tabpy.tabpy_server.handlers import (
    EndpointHandler,
    EndpointsHandler,
    EvaluationPlaneHandler,
    EvaluationPlaneDisabledHandler,
    QueryPlaneHandler,
    ServiceInfoHandler,
    StatusHandler,
    UploadDestinationHandler,
)

logger = logging.getLogger(__name__)

def _init_asyncio_patch():
    """
    Select compatible event loop for Tornado 5+.
    As of Python 3.8, the default event loop on Windows is `proactor`,
    however Tornado requires the old default "selector" event loop.
    As Tornado has decided to leave this to users to set, MkDocs needs
    to set it. See https://github.com/tornadoweb/tornado/issues/2608.
    """
    if sys.platform.startswith("win") and sys.version_info >= (3, 8):
        import asyncio
        try:
            from asyncio import WindowsSelectorEventLoopPolicy
        except ImportError:
            pass  # Can't assign a policy which doesn't exist.
        else:
            if not isinstance(asyncio.get_event_loop_policy(), WindowsSelectorEventLoopPolicy):
                asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())


class TabPyApp:
    """
    TabPy application class for keeping context like settings, state, etc.
    """

    settings = {}
    subdirectory = ""
    tabpy_state = None
    python_service = None
    credentials = {}
    arrow_server = None
    max_request_size = None

    def __init__(self, config_file, disable_auth_warning=True):
        self.disable_auth_warning = disable_auth_warning
        if config_file is None:
            config_file = os.path.join(
                os.path.dirname(__file__), os.path.pardir, "common", "default.conf"
            )

        if os.path.isfile(config_file):
            try:
                from logging import config
                config.fileConfig(config_file, disable_existing_loggers=False)
            except KeyError:
                logging.basicConfig(level=logging.DEBUG)

        self._parse_config(config_file)

    def _initialize_ssl_context(self):
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

        ssl_context.load_cert_chain(
            certfile=self.settings[SettingsParameters.CertificateFile],
            keyfile=self.settings[SettingsParameters.KeyFile]
        )

        min_tls = self.settings[SettingsParameters.MinimumTLSVersion]
        if not hasattr(ssl.TLSVersion, min_tls):
            logger.warning(f"Unrecognized value for TABPY_MINIMUM_TLS_VERSION: {min_tls}")
            min_tls = "TLSv1_2"
            
        logger.info(f"Setting minimum TLS version to {min_tls}") 
        ssl_context.minimum_version = ssl.TLSVersion[min_tls]

        return ssl_context

    def _get_tls_certificates(self, config):
        tls_certificates = []
        cert = config[SettingsParameters.CertificateFile]
        key = config[SettingsParameters.KeyFile]
        with open(cert, "rb") as cert_file:
            tls_cert_chain = cert_file.read()
        with open(key, "rb") as key_file:
            tls_private_key = key_file.read()
        tls_certificates.append((tls_cert_chain, tls_private_key))
        return tls_certificates
    
    def _get_arrow_server(self, config):
        verify_client = None
        tls_certificates = None
        scheme = "grpc+tcp"
        if config[SettingsParameters.TransferProtocol] == "https":
            scheme = "grpc+tls"
            tls_certificates = self._get_tls_certificates(config)

        host = "0.0.0.0"
        port = config.get(SettingsParameters.ArrowFlightPort)
        location = "{}://{}:{}".format(scheme, host, port)

        auth_middleware = None
        if "authentication" in config[SettingsParameters.ApiVersions]["v1"]["features"]:
            _, creds = parse_pwd_file(config[ConfigParameters.TABPY_PWD_FILE])
            auth_middleware = {
                "basic": BasicAuthServerMiddlewareFactory(creds)
            }

        server = pa.FlightServer(host, location,
                            tls_certificates=tls_certificates,
                            verify_client=verify_client, auth_handler=NoOpAuthHandler(),
                            middleware=auth_middleware)
        return server

    def run(self):
        application = self._create_tornado_web_app()
        
        init_model_evaluator(self.settings, self.tabpy_state, self.python_service)

        protocol = self.settings[SettingsParameters.TransferProtocol]
        ssl_options = None
        if protocol == "https":
            ssl_options = self._initialize_ssl_context()
        elif protocol != "http":
            msg = f"Unsupported transfer protocol {protocol}."
            logger.critical(msg)
            raise RuntimeError(msg)

        settings = {}
        if self.settings[SettingsParameters.GzipEnabled] is True:
            settings["decompress_request"] = True

        application.listen(
            self.settings[SettingsParameters.Port],
            ssl_options=ssl_options,
            max_buffer_size=self.max_request_size,
            max_body_size=self.max_request_size,
            **settings,
        ) 

        logger.info(
            "Web service listening on port "
            f"{str(self.settings[SettingsParameters.Port])}"
        )

        if self.settings[SettingsParameters.ArrowEnabled]:
            def start_pyarrow():
                pass

            try:
                _thread.start_new_thread(start_pyarrow, ())
            except Exception as e:
                logger.critical(f"Failed to start PyArrow server: {e}")

        tornado.ioloop.IOLoop.instance().start()

    def _create_tornado_web_app(self):
        class TabPyTornadoApp(tornado.web.Application):
            is_closing = False

            def signal_handler(self, signal, _):
                pass

            def try_exit(self):
                pass

        logger.info("Initializing TabPy...")
        tornado.ioloop.IOLoop.instance().run_sync(
            lambda: init_ps_server(self.settings, self.tabpy_state)
        )
        logger.info("Done initializing TabPy.")

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=multiprocessing.cpu_count()
        )

        # initialize Tornado application
        _init_asyncio_patch()
        application = TabPyTornadoApp(
            [
                (
                    self.subdirectory + r"/query/([^/]+)",
                    QueryPlaneHandler,
                    dict(app=self),
                ),
                (self.subdirectory + r"/status", StatusHandler, dict(app=self)),
                (self.subdirectory + r"/info", ServiceInfoHandler, dict(app=self)),
                (self.subdirectory + r"/endpoints", EndpointsHandler, dict(app=self)),
                (
                    self.subdirectory + r"/endpoints/([^/]+)?",
                    EndpointHandler,
                    dict(app=self),
                ),
                (
                    self.subdirectory + r"/evaluate",
                    EvaluationPlaneHandler if self.settings[SettingsParameters.EvaluateEnabled]
                    else EvaluationPlaneDisabledHandler,
                    dict(executor=executor, app=self),
                ),
                (
                    self.subdirectory + r"/configurations/endpoint_upload_destination",
                    UploadDestinationHandler,
                    dict(app=self),
                ),
                (
                    self.subdirectory + r"/(.*)",
                    tornado.web.StaticFileHandler,
                    dict(
                        path=self.settings[SettingsParameters.StaticPath],
                        default_filename="index.html",
                    ),
                ),
            ],
            debug=False,
            **self.settings,
        )

        signal.signal(signal.SIGINT, application.signal_handler)
        tornado.ioloop.PeriodicCallback(application.try_exit, 500).start()

        signal.signal(signal.SIGINT, application.signal_handler)
        tornado.ioloop.PeriodicCallback(application.try_exit, 500).start()

        return application

    def _set_parameter(self, parser, settings_key, config_key, default_val, parse_function):
        pass

    def _parse_config(self, config_file):
        """Provide consistent mechanism for pulling in configuration.

        Attempt to retain backward compatibility for
        existing implementations by grabbing port
        setting from CLI first.

        Take settings in the following order:

        1. CLI arguments if present
        2. config file
        3. OS environment variables (for ease of
           setting defaults if not present)
        4. current defaults if a setting is not present in any location

        Additionally provide similar configuration capabilities in between
        config file and environment variables.
        For consistency use the same variable name in the config file as
        in the os environment.
        For naming standards use all capitals and start with 'TABPY_'
        """
        pass

    def _validate_transfer_protocol_settings(self):
        pass

    @staticmethod
    def _validate_cert_key_state(msg, cert_valid, key_valid):
        pass

    def _parse_pwd_file(self):
        pass

    def _handle_configuration_without_authentication(self):
        pass

    def _get_features(self):
        pass

    def _build_tabpy_state(self):
        pass


# Override _read_body to allow content with size exceeding max_body_size
# This enables proper handling of 413 errors in base_handler
def _read_body_allow_max_size(self, code, headers, delegate):
    pass

HTTP1Connection.original_read_body = HTTP1Connection._read_body
HTTP1Connection._read_body = _read_body_allow_max_size
