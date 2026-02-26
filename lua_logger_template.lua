-- DuckStation Lua Script: Memory value logger
-- Reads specified PS1 memory addresses and writes to CSV at regular intervals.
--
-- Usage:
--   1. Edit the `addresses` table below with your discovered addresses
--   2. Place this script in ~/ps1-ai-player/
--   3. DuckStation will auto-load it if ScriptsDirectory is configured
--
-- The addresses table should match your addresses/{game_id}.json file.

-- Configuration
local LOG_INTERVAL = 300  -- Frames between log entries (300 = 5 seconds at 60fps)
local LOG_DIR = os.getenv("HOME") .. "/ps1-ai-player/logs/"
local GAME_ID = "UNKNOWN"

-- Address definitions: {name, address, type}
-- type: "byte" (uint8), "word" (uint16), "dword" (uint32)
-- Modify this table to match your game's discovered addresses
local addresses = {
    { name = "money",        address = 0x1F800000, type = "dword" },
    { name = "visitors",     address = 0x1F800004, type = "word"  },
    { name = "satisfaction", address = 0x1F800008, type = "byte"  },
    { name = "nausea",       address = 0x1F80000C, type = "byte"  },
    { name = "hunger",       address = 0x1F800010, type = "byte"  },
}

-- Internal state
local frame_count = 0
local log_file = nil
local log_path = ""

--- Read a memory value based on type string.
--- @param addr number Memory address
--- @param dtype string Data type: "byte", "word", or "dword"
--- @return number
local function read_typed(addr, dtype)
    if dtype == "byte" then
        return Memory.ReadByte(addr)
    elseif dtype == "word" then
        return Memory.ReadWord(addr)
    elseif dtype == "dword" then
        return Memory.ReadDWord(addr)
    else
        Console.WriteLn("Unknown type: " .. dtype)
        return 0
    end
end

--- Generate the CSV header line.
--- @return string
local function make_header()
    local parts = { "frame" }
    for _, entry in ipairs(addresses) do
        table.insert(parts, entry.name)
    end
    return table.concat(parts, ",")
end

--- Read all addresses and format as a CSV line.
--- @return string
local function make_row()
    local parts = { tostring(frame_count) }
    for _, entry in ipairs(addresses) do
        local val = read_typed(entry.address, entry.type)
        table.insert(parts, tostring(val))
    end
    return table.concat(parts, ",")
end

--- Initialize the log file.
local function init_log()
    -- Create timestamp-based filename
    local timestamp = os.date("%Y%m%d_%H%M%S")
    log_path = LOG_DIR .. timestamp .. "_" .. GAME_ID .. "_lua.csv"

    log_file = io.open(log_path, "w")
    if log_file then
        log_file:write(make_header() .. "\n")
        log_file:flush()
        Console.WriteLn("[Logger] Logging to: " .. log_path)
    else
        Console.WriteLn("[Logger] ERROR: Could not open log file: " .. log_path)
    end
end

--- Write a log entry if the interval has elapsed.
local function update_log()
    if log_file == nil then
        return
    end

    if frame_count % LOG_INTERVAL == 0 then
        local row = make_row()
        log_file:write(row .. "\n")
        log_file:flush()

        -- Also print to DuckStation console
        if frame_count % (LOG_INTERVAL * 12) == 0 then  -- Every ~60 seconds
            Console.WriteLn("[Logger] Frame " .. frame_count .. ": " .. row)
        end
    end
end

--- Close the log file cleanly.
local function close_log()
    if log_file then
        log_file:close()
        log_file = nil
        Console.WriteLn("[Logger] Log saved to: " .. log_path)
    end
end

-- Callbacks

--- Called once when the script loads.
function OnScriptLoaded()
    Console.WriteLn("[Logger] PS1 Memory Logger loaded")
    Console.WriteLn("[Logger] Tracking " .. #addresses .. " parameters")
    Console.WriteLn("[Logger] Log interval: " .. LOG_INTERVAL .. " frames")

    -- Ensure log directory exists
    os.execute("mkdir -p " .. LOG_DIR)

    init_log()
end

--- Called every frame.
function UpdatePerFrame()
    frame_count = frame_count + 1
    update_log()
end

--- Called when the script is unloaded or emulator closes.
function OnScriptUnloaded()
    close_log()
    Console.WriteLn("[Logger] Logger unloaded")
end
