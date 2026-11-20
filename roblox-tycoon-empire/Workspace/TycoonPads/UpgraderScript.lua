-- Script inside Upgrader Part
local upgrader = script.Parent
local multiplier = 1.5
local debounce = {}

upgrader.Touched:Connect(function(hit)
	local val = hit:FindFirstChild("Value")
	if val and not debounce[hit] then
		debounce[hit] = true
		val.Value = math.floor(val.Value * multiplier)
		hit.BrickColor = BrickColor.new("Bright orange")
		wait(0.5)
		debounce[hit] = nil
	end
end)
