-- ServerScriptService > LeaderstatsScript
game.Players.PlayerAdded:Connect(function(player)
	local leaderstats = Instance.new("Folder")
	leaderstats.Name = "leaderstats"
	leaderstats.Parent = player

	local cash = Instance.new("IntValue")
	cash.Name = "Cash"
	cash.Value = 100
	cash.Parent = leaderstats

	local rebirth = Instance.new("IntValue")
	rebirth.Name = "Rebirth"
	rebirth.Value = 0
	rebirth.Parent = leaderstats
end)
