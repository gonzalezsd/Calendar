BEGIN;

LOCK TABLE tipos_fecha IN SHARE ROW EXCLUSIVE MODE;

CREATE UNIQUE INDEX IF NOT EXISTS tipos_fecha_festivo_unico ON tipos_fecha (nombre)
    WHERE nombre = 'Festivo';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM tipos_fecha
        WHERE nombre = 'Festivo'
          AND (descripcion IS DISTINCT FROM 'Día festivo'
               OR color IS DISTINCT FROM '#FF0000'
               OR en_borde IS DISTINCT FROM false)
    ) THEN
        RAISE EXCEPTION 'El tipo Festivo existente no coincide con los datos básicos; revísalo antes de continuar';
    END IF;

    INSERT INTO tipos_fecha (nombre, descripcion, color, en_borde)
    SELECT 'Festivo', 'Día festivo', '#FF0000', false
    WHERE NOT EXISTS (SELECT 1 FROM tipos_fecha WHERE nombre = 'Festivo');
END $$;

COMMIT;
