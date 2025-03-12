#!/usr/bin/env python3
"""
Database initialization script for MCP PaaS.

This script:
1. Creates tables for tenants and API keys
2. Sets up foreign key relationships
3. Creates a test tenant with an API key
"""

import os
import sys
import uuid
import sqlite3
import secrets
import datetime
from pathlib import Path

# Add the parent directory to the path to allow imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from mcp_paas.config import settings

# Database path
DB_PATH = Path(settings.DATABASE.PATH)

# Ensure directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

print(f"Initializing database at {DB_PATH}...")

# Create database connection
conn = sqlite3.connect(str(DB_PATH))
conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
cursor = conn.cursor()

# Create tenants table
cursor.execute('''
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    max_contexts INTEGER NOT NULL,
    max_tokens_per_min INTEGER NOT NULL,
    max_requests_per_min INTEGER NOT NULL,
    max_context_ttl_seconds INTEGER NOT NULL
)
''')

# Create API keys table
cursor.execute('''
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP,
    last_used_at TIMESTAMP,
    is_active BOOLEAN NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
)
''')

# Create indexes for performance
cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_id ON api_keys(tenant_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash)')

# Check if test tenant already exists
cursor.execute("SELECT id FROM tenants WHERE name = 'Test Tenant'")
test_tenant = cursor.fetchone()

if test_tenant:
    print(f"Test tenant already exists with ID: {test_tenant[0]}")
    tenant_id = test_tenant[0]
else:
    # Create a test tenant
    tenant_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    
    cursor.execute('''
    INSERT INTO tenants (
        id, name, email, status, created_at, updated_at,
        max_contexts, max_tokens_per_min, max_requests_per_min, max_context_ttl_seconds
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        tenant_id, 
        'Test Tenant', 
        'test@example.com', 
        'active',
        now, 
        now,
        10,  # max_contexts
        10000,  # max_tokens_per_min
        100,  # max_requests_per_min
        3600  # max_context_ttl_seconds (1 hour)
    ))
    
    print(f"Created test tenant with ID: {tenant_id}")

# Create an API key for the test tenant
api_key_id = str(uuid.uuid4())
api_key = secrets.token_urlsafe(32)  # Generate a random API key
api_key_hash = api_key  # In a real app, you'd hash this with bcrypt or similar

# Check if API key already exists
cursor.execute("SELECT id FROM api_keys WHERE tenant_id = ? AND name = 'Test API Key'", (tenant_id,))
existing_key = cursor.fetchone()

if existing_key:
    print(f"Test API key already exists with ID: {existing_key[0]}")
else:
    now = datetime.datetime.utcnow().isoformat()
    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
    
    cursor.execute('''
    INSERT INTO api_keys (
        id, tenant_id, key_hash, name, created_at, expires_at, is_active
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        api_key_id,
        tenant_id,
        api_key_hash,
        'Test API Key',
        now,
        expires_at,
        True
    ))
    
    print(f"Created API key for test tenant: {api_key}")
    print("⚠️  IMPORTANT: Save this API key as it won't be shown again!")

# Commit changes and close connection
conn.commit()
conn.close()

print("Database initialization complete!")

