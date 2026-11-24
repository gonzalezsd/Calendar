BEGIN;

ALTER TABLE proyectos ADD COLUMN activo boolean NOT NULL DEFAULT false;
ALTER TABLE tipos_fecha ADD COLUMN activo boolean NOT NULL DEFAULT false;

COMMIT;
