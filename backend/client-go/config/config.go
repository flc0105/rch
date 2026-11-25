package config

// Build-time connection settings. Both directions default to TCP.
var SERVER_ADDR = "127.0.0.1:9999"
var SERVER_TRANSPORT = "tcp"
var CONNECTION_MODE = "reverse"
var BIND_HOST = "0.0.0.0"
var BIND_PORT = 9443
var IDENTITY_DIR = ""
var SERVER_WEB_SCHEME = "http"
var SERVER_WEB_HOST = "127.0.0.1"
var SERVER_WEB_PORT = 8085
var UPLOAD_BASE_URL = SERVER_WEB_SCHEME + "://" + SERVER_WEB_HOST + ":" + "8085"
var CLIENT_BUILD_VERSION = "dev"
