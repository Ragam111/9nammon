-- Script inside Conveyor Belt Part
local conveyor = script.Parent
local speed = 10

conveyor.Touched:Connect(function(hit)
	if hit:FindFirstChild("Value") then
		hit.Velocity = conveyor.CFrame.LookVector * speed
	end
end)
