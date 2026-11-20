BEGIN;

LOCK TABLE proyectos IN SHARE ROW EXCLUSIVE MODE;

CREATE UNIQUE INDEX IF NOT EXISTS proyectos_vacaciones_unico ON proyectos (nombre)
    WHERE nombre = 'Vacaciones';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM proyectos
        WHERE nombre = 'Vacaciones'
          AND (color IS DISTINCT FROM '#FF7800'
               OR duracion IS DISTINCT FROM NULL
               OR restantes IS DISTINCT FROM NULL)
    ) THEN
        RAISE EXCEPTION 'El proyecto Vacaciones existente no coincide con los datos básicos; revísalo antes de continuar';
    END IF;

    INSERT INTO proyectos (nombre, duracion, restantes, color)
    SELECT 'Vacaciones', NULL, NULL, '#FF7800'
    WHERE NOT EXISTS (SELECT 1 FROM proyectos WHERE nombre = 'Vacaciones');
END $$;

COMMIT;
