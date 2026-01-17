BEGIN;

-- Tear down in dependency order
DROP TABLE IF EXISTS assets CASCADE;
DROP TABLE IF EXISTS rooms CASCADE;
DROP TABLE IF EXISTS locations CASCADE;

-- Shared trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- LOCATIONS
CREATE TABLE locations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT,
    head TEXT,
    phone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER trg_locations_set_updated_at
BEFORE UPDATE ON locations
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ROOMS (belongs to locations)
CREATE TABLE rooms (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    floor INTEGER,
    location_id INTEGER NOT NULL
        REFERENCES locations(id)
        ON DELETE RESTRICT     -- blocks deleting a location with rooms
        ON UPDATE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_rooms_location_id ON rooms(location_id);
CREATE UNIQUE INDEX ux_rooms_location_name ON rooms(location_id, name);
CREATE TRIGGER trg_rooms_set_updated_at
BEFORE UPDATE ON rooms
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ASSETS (belongs to rooms)
-- Use a surrogate PK (id) + human-readable asset_code (text)
CREATE TABLE assets (
    id SERIAL PRIMARY KEY,
    asset_code TEXT NOT NULL
        CHECK (asset_code ~ '^\d{3}-\d{3}-\d{5}$')  -- e.g. 001-001-98152
        UNIQUE,
    name TEXT NOT NULL,
    room_id INTEGER NOT NULL
        REFERENCES rooms(id)
        ON DELETE RESTRICT     -- blocks deleting a room with assets
        ON UPDATE CASCADE,
    category TEXT,
    price NUMERIC(12,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- convenient parsed parts
    location_code TEXT GENERATED ALWAYS AS (split_part(asset_code, '-', 1)) STORED,
    room_code     TEXT GENERATED ALWAYS AS (split_part(asset_code, '-', 2)) STORED,
    seq_no        TEXT GENERATED ALWAYS AS (split_part(asset_code, '-', 3)) STORED
);

CREATE INDEX idx_assets_room_id    ON assets(room_id);
CREATE INDEX idx_assets_category   ON assets(category);
CREATE INDEX idx_assets_location_code ON assets(location_code);
CREATE INDEX idx_assets_room_code  ON assets(room_code);
CREATE UNIQUE INDEX ux_assets_room_name ON assets(room_id, name);

CREATE TRIGGER trg_assets_set_updated_at
BEFORE UPDATE ON assets
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMIT;
