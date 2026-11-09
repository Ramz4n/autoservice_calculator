class UserModel {
  final int id;
  final String email;
  final String? fullName;
  final String? phone;
  final String role;
  final DateTime createdAt;

  UserModel({
    required this.id,
    required this.email,
    this.fullName,
    this.phone,
    required this.role,
    required this.createdAt,
  });

  factory UserModel.fromJson(Map<String, dynamic> json) {
    return UserModel(
      id: json['id'] as int,
      email: json['email'] as String,
      fullName: json['full_name'] as String?,
      phone: json['phone'] as String?,
      role: json['role'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }

  String get displayName => fullName?.isNotEmpty == true ? fullName! : email;
  String get initials => displayName.substring(0, 1).toUpperCase();
}
