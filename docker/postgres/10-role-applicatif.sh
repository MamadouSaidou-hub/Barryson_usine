#!/bin/sh
# Cree (ou resynchronise) le compte de connexion de l'API.
#
# Execute automatiquement par l'image postgres au premier demarrage d'un volume
# vierge. Sur une base existante, le lancer une fois a la main :
#   docker compose exec db sh /docker-entrypoint-initdb.d/10-role-applicatif.sh
#
# Le compte n'a aucun privilege d'administration. Ses droits sur les tables
# viennent du groupe barryson_app_droits, regle par les migrations.
# Les valeurs passent par des variables psql (:'...') et non par le shell :
# un mot de passe contenant une apostrophe ne peut pas injecter de SQL.
set -eu

psql -v ON_ERROR_STOP=1 \
     -v app_user="$POSTGRES_APP_USER" \
     -v app_password="$POSTGRES_APP_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
SELECT 'CREATE ROLE barryson_app_droits NOLOGIN'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'barryson_app_droits') \gexec

SELECT format('CREATE ROLE %I LOGIN', :'app_user')
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT',
              :'app_user', :'app_password') \gexec

SELECT format('GRANT barryson_app_droits TO %I', :'app_user') \gexec

-- Personne d'autre que le proprietaire ne cree d'objet dans le schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
EOSQL
