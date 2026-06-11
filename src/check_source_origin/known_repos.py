from __future__ import annotations

import re

KNOWN_REPOS: dict[str, str] = {
    "adlfs": "https://github.com/fsspec/adlfs",
    "aliyun-python-sdk-kms": "https://github.com/aliyun/aliyun-openapi-python-sdk",
    "antlr4-python3-runtime": "https://github.com/antlr/antlr4",
    "arro3-core": "https://github.com/kylebarron/arro3",
    "avro": "https://github.com/apache/avro",
    "coloredlogs": "https://github.com/xolox/python-coloredlogs",
    "contextlib2": "https://github.com/jazzband/contextlib2",
    "databricks-sdk": "https://github.com/databricks/databricks-sdk-py",
    "dbt-semantic-interfaces": "https://github.com/dbt-labs/dbt-semantic-interfaces",
    "decorator": "https://github.com/micheles/decorator",
    "detect-installer": "https://github.com/patrick91/detect-installer",
    "docopt": "https://github.com/docopt/docopt",
    "docutils": "https://github.com/docutils/docutils",
    "envoy-data-plane": "https://github.com/cetanu/envoy_data_plane",
    "gremlinpython": "https://github.com/apache/tinkerpop",
    "griffelib": "https://github.com/mkdocstrings/griffe",
    "grpcio-health-checking": "https://github.com/grpc/grpc",
    "grpcio-reflection": "https://github.com/grpc/grpc",
    "grpcio-status": "https://github.com/grpc/grpc",
    "httpx": "https://github.com/encode/httpx",
    "humanfriendly": "https://github.com/xolox/python-humanfriendly",
    "langfuse": "https://github.com/langfuse/langfuse-python",
    "lockfile": "https://github.com/openstack-archive/pylockfile",
    "looker-sdk": "https://github.com/looker-open-source/sdk-codegen",
    "mando": "https://github.com/rubik/mando",
    "namex": "https://github.com/fchollet/namex",
    "nexus-rpc": "https://github.com/nexus-rpc/sdk-python",
    "opt-einsum": "https://github.com/dgasmith/opt_einsum",
    "optuna": "https://github.com/optuna/optuna",
    "oss2": "https://github.com/aliyun/aliyun-oss-python-sdk",
    "pbr": "https://github.com/openstack/pbr",
    "ply": "https://github.com/dabeaz/ply",
    "protobuf": "https://github.com/protocolbuffers/protobuf",
    "purecloudplatformclientv2": "https://github.com/MyPureCloud/platform-client-sdk-python",
    "py": "https://github.com/pytest-dev/py",
    "py-key-value-aio": "https://github.com/strawgate/py-key-value",
    "py-key-value-shared": "https://github.com/strawgate/py-key-value",
    "py4j": "https://github.com/py4j/py4j",
    "pycodestyle": "https://github.com/PyCQA/pycodestyle",
    "pycrypto": "https://github.com/pycrypto/pycrypto",
    "pydub": "https://github.com/jiaaro/pydub",
    "pyre": "https://github.com/pyre/pyre",
    "reportlab": "https://github.com/MrBitBucket/reportlab-mirror",
    "rfc3986": "https://github.com/python-hyper/rfc3986",
    "rich-toolkit": "https://github.com/patrick91/rich-toolkit",
    "rignore": "https://github.com/patrick91/rignore",
    "rsa": "https://github.com/sybrenstuvel/python-rsa",
    "selenium": "https://github.com/SeleniumHQ/selenium",
    "snowplow-tracker": "https://github.com/snowplow/snowplow-python-tracker",
    "sortedcontainers": "https://github.com/grantjenks/python-sortedcontainers",
    "spacy-legacy": "https://github.com/explosion/spacy-legacy",
    "synchronicity": "https://github.com/modal-labs/synchronicity",
    "thrift": "https://github.com/apache/thrift",
    "unidecode": "https://github.com/avian2/unidecode",
    "uri-template": "https://github.com/plinss/uri-template",
    "widgetsnbextension": "https://github.com/jupyter-widgets/ipywidgets",
    "workos": "https://github.com/workos/workos-python",
    "xlrd": "https://github.com/python-excel/xlrd",
    "zict": "https://github.com/dask/zict",
}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def lookup(name: str) -> str | None:
    return KNOWN_REPOS.get(_normalize(name))
