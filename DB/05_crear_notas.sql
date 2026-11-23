CREATE TABLE notas (
    usuario_id integer NOT NULL REFERENCES usuarios (usuario_id),
    fecha date NOT NULL,
    texto text NOT NULL,
    PRIMARY KEY (usuario_id, fecha)
);
