```
@startuml erd
!include https://github.com/polyrex/projec1/blob/main/attributes.pu
!include https://github.com/polyrex/projec1/blob/main/tables.pu

companies ||-o{ users

hide positions
hide user_positions
hide user_subordinate_users
hide user_profiles

@enduml
```
