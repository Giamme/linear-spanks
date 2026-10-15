---
name: tech-docker
description: Technology skill loaded when writing or modifying Dockerfiles or docker-compose.yml.
---
# Docker Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When containerizing applications, optimize for image size, build speed, and security:

1. **Multi-Stage Builds**: Always use multi-stage builds for compiled languages or build steps (like Node/React) to keep the final production image small.
2. **Base Images**: Use minimal base images (e.g., `alpine`, `slim`, or `distroless`) unless specific system dependencies are required.
3. **Layer Caching**: Order `Dockerfile` instructions from least frequently changed to most frequently changed. Copy package files (`package.json`, `requirements.txt`) and install dependencies *before* copying the source code.
4. **Security**: Never run the application as the `root` user. Explicitly create and switch to a non-root `USER`.
5. **Secrets**: Never bake secrets or `.env` files into the image. Use environment variables at runtime or Docker Secrets.
