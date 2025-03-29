#!/usr/bin/env bash
# exit on error
set -o errexit

echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Making migrations..."
python manage.py makemigrations --noinput

# Drop and recreate schema with proper permissions
echo "Setting up database schema..."
python manage.py dbshell << EOF
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
ALTER SCHEMA public OWNER TO whoswhodb_user;
GRANT ALL ON SCHEMA public TO whoswhodb_user;
GRANT ALL ON SCHEMA public TO public;
ALTER DATABASE whoswhodb OWNER TO whoswhodb_user;
ALTER DEFAULT PRIVILEGES FOR USER whoswhodb_user IN SCHEMA public GRANT ALL ON TABLES TO whoswhodb_user;
ALTER DEFAULT PRIVILEGES FOR USER whoswhodb_user IN SCHEMA public GRANT ALL ON SEQUENCES TO whoswhodb_user;
ALTER DEFAULT PRIVILEGES FOR USER whoswhodb_user IN SCHEMA public GRANT ALL ON FUNCTIONS TO whoswhodb_user;
EOF

echo "Applying migrations..."
# Show migrations status before applying
echo "Current migration status:"
python manage.py showmigrations

# First migrate auth and contenttypes
echo "Migrating auth and contenttypes first..."
python manage.py migrate auth zero --noinput || true
python manage.py migrate contenttypes zero --noinput || true

echo "Applying auth migrations..."
python manage.py migrate contenttypes --noinput
python manage.py migrate auth --noinput

# Then migrate the rest
echo "Migrating remaining apps..."
python manage.py migrate admin --noinput
python manage.py migrate sessions --noinput
python manage.py migrate WhosWhoApp --noinput

# Finally run any remaining migrations
echo "Running remaining migrations..."
python manage.py migrate --noinput

# Verify migrations after applying
echo "Final migration status:"
python manage.py showmigrations

# Grant permissions on all tables
echo "Setting table permissions..."
python manage.py dbshell << EOF
DO \$\$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('GRANT ALL ON TABLE %I TO whoswhodb_user', r.tablename);
        EXECUTE format('ALTER TABLE %I OWNER TO whoswhodb_user', r.tablename);
    END LOOP;
    FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' LOOP
        EXECUTE format('GRANT ALL ON SEQUENCE %I TO whoswhodb_user', r.sequencename);
        EXECUTE format('ALTER SEQUENCE %I OWNER TO whoswhodb_user', r.sequencename);
    END LOOP;
END \$\$;
EOF

echo "Collecting static files..."
python manage.py collectstatic --no-input

# Create superuser if DJANGO_SUPERUSER_USERNAME is set
if [[ -n "${DJANGO_SUPERUSER_USERNAME}" ]]; then
    echo "Creating superuser..."
    DJANGO_SUPERUSER_PASSWORD=${DJANGO_SUPERUSER_PASSWORD} python manage.py createsuperuser \
        --noinput \
        --username $DJANGO_SUPERUSER_USERNAME \
        --email $DJANGO_SUPERUSER_EMAIL
fi
