-- Script inside Dropper Part
local dropper = script.Parent
local dropPart = dropper:FindFirstChild("DropPart")

while true do
	wait(2)
	local item = Instance.new("Part")
	item.Size = Vector3.new(1, 1, 1)
	item.BrickColor = BrickColor.new("Gold")
	item.Position = dropPart.Position - Vector3.new(0, 2, 0)
	item.Parent = workspace

	local val = Instance.new("IntValue")
	val.Name = "Value"
	val.Value = 5
	val.Parent = item

	game.Debris:AddItem(item, 15)
end
