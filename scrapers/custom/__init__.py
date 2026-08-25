"""
사이트 고유의 절차(로그인, 팝업 닫기, 다단계 메뉴 클릭 등)가 필요한 곳을 위한
전용 핸들러 모음. site_registry.py의 CUSTOM_HANDLER_DOMAINS에 도메인을 등록하고,
engine.py의 CUSTOM_HANDLERS 매핑에 함수를 연결하면 새 사이트를 추가할 수 있다.
"""

from . import khnp, igunsul  # noqa: F401
