```
@startuml erd
!include https://github.com/murataSandbox/metadata-management/raw/refs/heads/main/er/attributes.pu
!include https://github.com/murataSandbox/metadata-management/raw/refs/heads/main/er/tables.pu

companies ||-o{ users

hide positions
hide user_positions
hide user_subordinate_users
hide user_profiles

@enduml
```
