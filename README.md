# SwaggerToPy
This repository is the application files for an HTML frontend application that allows swagger descriptor files to be digested into a python class. This will facilitate software developers using APIs.

The backend is a single Go binary that serves the static HTML and exposes `POST /api/convert`, which accepts a Swagger / OpenAPI JSON body and returns the generated Python class.

## Build

    go build -o swaggertopy

## Run

    ./swaggertopy                  # listens on :2323 (default)
    ./swaggertopy -port 8080       # override via flag
    PORT=8080 ./swaggertopy        # override via env var

The `-port` flag is intended for use by configuration management (e.g. Puppet) — assign whatever port the host has free.

Other flags:

- `-addr` — bind address (default `0.0.0.0`)
- `-html` — directory containing static assets (default `html`)


# License

This is released under a standard MIT license
