class VehicleCapabilities {
  const VehicleCapabilities({
    required this.manualDrive,
    required this.pathPlanning,
    required this.pathExecution,
    required this.localization,
    required this.printing,
    required this.emergencyStop,
  });

  factory VehicleCapabilities.fromJson(Map<String, dynamic> json) {
    return VehicleCapabilities(
      manualDrive: json['manual_drive'] == true,
      pathPlanning: json['path_planning'] == true,
      pathExecution: json['path_execution'] == true,
      localization: json['localization'] == true,
      printing: json['printing'] == true,
      emergencyStop: json['emergency_stop'] == true,
    );
  }

  final bool manualDrive;
  final bool pathPlanning;
  final bool pathExecution;
  final bool localization;
  final bool printing;
  final bool emergencyStop;
}

class VehicleStatus {
  const VehicleStatus({
    required this.deviceId,
    required this.model,
    required this.softwareVersion,
    required this.online,
    required this.rosAvailable,
    required this.controlReady,
    required this.localizationValid,
    required this.localizationSource,
    required this.emergencyStopped,
    required this.capabilities,
  });

  factory VehicleStatus.fromEnvelope(Map<String, dynamic> envelope) {
    final vehicle = _map(envelope['vehicle']);
    final runtime = _map(vehicle['runtime']);
    final safety = _map(vehicle['safety']);
    final localization = _map(vehicle['localization']);
    return VehicleStatus(
      deviceId: vehicle['device_id']?.toString() ?? '',
      model: vehicle['model']?.toString() ?? '',
      softwareVersion: vehicle['software_version']?.toString() ?? '',
      online: runtime['online'] == true || envelope['online'] == true,
      rosAvailable:
          runtime['ros_available'] == true || envelope['ros_available'] == true,
      controlReady:
          runtime['control_ready'] == true || envelope['control_ready'] == true,
      localizationValid:
          localization['valid'] == true ||
          envelope['localization_valid'] == true,
      localizationSource:
          localization['source']?.toString() ??
          envelope['localization_source']?.toString() ??
          'unavailable',
      emergencyStopped:
          safety['emergency_stopped'] == true ||
          envelope['emergency_stopped'] == true,
      capabilities: VehicleCapabilities.fromJson(_map(vehicle['capabilities'])),
    );
  }

  final String deviceId;
  final String model;
  final String softwareVersion;
  final bool online;
  final bool rosAvailable;
  final bool controlReady;
  final bool localizationValid;
  final String localizationSource;
  final bool emergencyStopped;
  final VehicleCapabilities capabilities;

  static Map<String, dynamic> _map(Object? value) =>
      value is Map ? Map<String, dynamic>.from(value) : const {};
}
