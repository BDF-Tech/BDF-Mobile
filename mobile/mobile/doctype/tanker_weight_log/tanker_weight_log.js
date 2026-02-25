// Function to update the tank visual
function updateTankGraphic(deviceId, maxCapacity = 5000) {
    frappe.db.get_list('Tanker Weight Log', {
        filters: { 'device': deviceId },
        fields: ['weight'],
        order_by: 'creation desc',
        limit: 1
    }).then(records => {
        if (records.length > 0) {
            let weight = records[0].weight;
            let fillPercent = (weight / maxCapacity) * 100;
            
            // Limit to 100% so it doesn't overflow the graphic
            if (fillPercent > 100) fillPercent = 100;

            // Update UI
            document.getElementById('liquid-level').style.height = fillPercent + '%';
            document.getElementById('weight-display').innerText = weight + ' kg';
            document.getElementById('device-label').innerText = "Device: " + deviceId;
            
            // Change color if empty (Red) or near full (Green)
            let color = fillPercent < 10 ? '#f44336' : '#2196F3';
            document.getElementById('liquid-level').style.backgroundColor = color;
        }
    });
}

// Run every 30 seconds
setInterval(() => updateTankGraphic('MCOMWIFI051'), 30000);
updateTankGraphic('MCOMWIFI051'); // Initial call