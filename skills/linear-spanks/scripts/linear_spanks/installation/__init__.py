"""Installers, extension management, client resolution, and model routing."""

from .clients import ClientRegistry, ClientSpec, client_registry

__all__ = ["ClientRegistry", "ClientSpec", "client_registry"]
