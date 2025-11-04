# PyVest - Harvest Time Tracking Data Exporter

Script Python pour exporter les données de temps de Harvest et les sauvegarder sur AWS S3.
Peut être exécuté localement ou déployé en tant qu'AWS Lambda.

## Fonctionnalités

- Exporte les données des 90 derniers jours depuis Harvest (configurable)
- Sauvegarde automatique vers AWS S3
- Gestion des mises à jour et suppressions dans les fichiers S3
- Tri chronologique des données
- Compatible AWS Lambda avec support IAM roles

---

## 🚀 Déploiement AWS Lambda

### Prérequis

1. Un compte AWS avec accès à Lambda, S3 et IAM
2. Un bucket S3 créé
3. Les credentials Harvest (Account ID et Access Token)

### Étape 1: Créer le bucket S3

1. Dans AWS Console, utilisez la barre de recherche en haut et tapez "S3"
2. Sélectionnez "S3" dans les résultats
3. Cliquez sur **"Create bucket"**
4. Configurez le bucket :
   - **Bucket name**: `harvest-dump` (ou un autre nom unique)
   - **AWS Region**: Sélectionnez votre région préférée (ex: `us-east-1`)
5. Laissez les autres paramètres par défaut ou configurez-les selon vos besoins
6. Cliquez sur **"Create bucket"**
7. Notez le nom du bucket et la région

### Étape 2: Créer un rôle IAM pour Lambda

1. Dans AWS Console, utilisez la barre de recherche et tapez "IAM"
2. Allez dans **IAM** > **Roles** (dans le menu de gauche)
3. Cliquez sur **"Create role"**
4. Sélectionnez **"AWS service"** comme type de trusted entity
5. Sélectionnez **"Lambda"** dans les cas d'usage
6. Cliquez sur **"Next"**
7. Sur la page **"Add permissions"** :
   
   **Option A : Attacher les policies maintenant (recommandé pour la simplicité)**
   
   **a) Créer la policy S3 d'abord (dans un nouvel onglet) :**
   - Ouvrez un nouvel onglet dans votre navigateur et allez dans **IAM** > **Policies**
   - Cliquez sur **"Create policy"**
   - Sélectionnez l'onglet **"JSON"**
   - Remplacez le contenu par (remplacez `votre-bucket-name` par le nom de votre bucket) :

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject"
            ],
            "Resource": "arn:aws:s3:::votre-bucket-name/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket"
            ],
            "Resource": "arn:aws:s3:::votre-bucket-name"
        }
    ]
}
```

   - Cliquez sur **"Next"**
   - Donnez un nom à la policy : `PyVestS3Access`
   - Cliquez sur **"Create policy"**
   
   **b) Retournez à l'onglet de création de rôle :**
   - Dans la page "Add permissions", cliquez sur le bouton de rafraîchissement (ou recherchez)
   - Recherchez et cochez **"PyVestS3Access"** (la policy que vous venez de créer)
   - Recherchez et cochez **"AWSLambdaBasicExecutionRole"** (policy AWS managed)
   
8. Cliquez sur **"Next"**

9. Sur la page **"Name, review, and create"** :
   - **Role name**: `PyVestLambdaRole` (ou un autre nom)
   - Vérifiez que les deux policies sont listées
   - Cliquez sur **"Create role"**

10. Notez l'ARN du rôle créé (vous en aurez besoin à l'étape 4)

**Note :** Si vous préférez, vous pouvez créer le rôle avec seulement `AWSLambdaBasicExecutionRole` et ajouter la policy S3 après en éditant le rôle.

### Étape 3: Préparer le package de déploiement

**Option A : Utiliser le script automatisé (recommandé)**

Exécutez simplement le script Python qui automatise tout le processus :

```bash
python create-lambda-package.py
```

Le script va :
- Créer le répertoire `lambda-package`
- Installer les dépendances
- Copier `pyvest.py`
- Créer le fichier `pyvest-lambda.zip`

**Option B : Création manuelle**

1. Créez un répertoire pour le package :
```bash
mkdir lambda-package
cd lambda-package
```

2. Installez les dépendances dans ce répertoire :
```bash
pip install --no-user -r ../requirements.txt -t .
```

**Note :** Le flag `--no-user` est nécessaire si pip a `--user` activé par défaut (erreur "Can not combine '--user' and '--target'").

3. Copiez le fichier Python :
```bash
cp ../pyvest.py .
```

4. Créez une archive ZIP :

**Sous Windows (avec Python) :**
```bash
python -c "import shutil; shutil.make_archive('../pyvest-lambda', 'zip', '.')"
```

**Sous Linux/Mac (avec zip) :**
```bash
zip -r ../pyvest-lambda.zip .
```

### Étape 4: Créer la fonction Lambda

1. Dans AWS Console, utilisez la barre de recherche en haut et tapez "Lambda"
2. Sélectionnez "Lambda" dans les résultats
3. Sur la page Lambda Functions, cliquez sur "Create function"
4. Configurez :
   - **Function name**: `pyvest-harvest-export`
   - **Runtime**: Python 3.11 ou Python 3.12 (selon votre préférence)
   - **Architecture**: x86_64 (ou arm64 si vous préférez)
   - **Permissions**: Sélectionnez "Use an existing role"
   - **Existing role**: Sélectionnez le rôle créé à l'étape 2 (ex: `PyVestLambdaRole`)

5. Cliquez sur "Create function"

### Étape 5: Uploader le code

1. Sur la page de la fonction Lambda, allez dans l'onglet **"Code"** (en haut de la page)
2. Cliquez sur "Upload from" dans le coin supérieur droit
3. Sélectionnez **"Upload a .zip file"**
4. Cliquez sur "Upload" et sélectionnez le fichier `pyvest-lambda.zip` créé à l'étape 3
5. Attendez que le téléchargement se termine

### Étape 5b: Configurer le handler

1. Toujours dans l'onglet **"Code"**, allez dans **"Runtime settings"**
2. Cliquez sur "Edit"
3. Configurez le **Handler** : `pyvest.lambda_handler`
4. Cliquez sur "Save"

### Étape 6: Configurer les variables d'environnement

Les variables d'environnement permettent à votre fonction Lambda d'accéder aux credentials Harvest et à la configuration S3 sans hardcoder les valeurs dans le code.

1. Sur la page de la fonction Lambda, allez dans l'onglet **"Configuration"** (en haut de la page)
2. Dans le menu de gauche, sélectionnez **"Environment variables"**
3. Cliquez sur **"Edit"**
4. Cliquez sur **"Add environment variable"** pour chaque variable à ajouter

5. Ajoutez les variables suivantes une par une :

#### Variables requises :

| Variable | Description | Exemple | Comment obtenir |
|----------|-------------|---------|----------------|
| `HARVEST_ACCOUNT_ID` | Votre Harvest Account ID (obligatoire) | `1339925` | Dans Harvest : Settings > Personal API > Account ID |
| `HARVEST_ACCESS_TOKEN` | Votre Harvest Personal Access Token (obligatoire) | `2421489.pt.Uac1i...` | Dans Harvest : Settings > Personal API > Create a Personal Access Token |
| `S3_BUCKET_NAME` | Nom de votre bucket S3 (obligatoire) | `harvest-dump` | Le nom du bucket créé à l'Étape 1 |

#### Variables optionnelles :

| Variable | Description | Valeur par défaut | Quand l'utiliser |
|----------|-------------|-------------------|-----------------|
| `HARVEST_URL` | URL de l'API Harvest | `https://api.harvestapp.com/v2/time_entries` | Laissez vide sauf si vous utilisez une URL personnalisée |
| `DAYS_BACK` | Nombre de jours en arrière pour récupérer les données | `90` | Définissez à `21`, `30`, `60`, etc. selon vos besoins |
| `AWS_REGION` | Région AWS pour S3 | Déduit automatiquement | Utilisé seulement si nécessaire (généralement déduit automatiquement) |

**Exemple de configuration complète :**
```
HARVEST_ACCOUNT_ID = 1339925
HARVEST_ACCESS_TOKEN = 2421489.pt.Uac1iLpnRXnegrIuw5KXryx4IvXu_GLvOaFDBH8ORMOPttzKQTh4XfR1QF8TSIubu3UmFefngYGrVy2vXnfhHQ
S3_BUCKET_NAME = harvest-dump
DAYS_BACK = 21
```

6. Pour chaque variable :
   - Entrez le **Key** (nom de la variable)
   - Entrez la **Value** (valeur de la variable)
   - Cliquez sur **"Add environment variable"** pour ajouter une autre variable

7. Une fois toutes les variables ajoutées, cliquez sur **"Save"** en bas de la page

**Note importante :** 
- Les valeurs sensibles comme `HARVEST_ACCESS_TOKEN` sont stockées dans l'environnement Lambda. Pour une sécurité renforcée, vous pouvez utiliser **AWS Systems Manager Parameter Store** avec des variables chiffrées :
  - Dans l'onglet "Environment variables", vous pouvez sélectionner "Use encryption helpers"
  - Créez une variable chiffrée avec AWS KMS ou utilisez Parameter Store
  - Référencez-la via `{{resolve:ssm:/path/to/parameter:1}}`

**Vérification :**
Après avoir sauvegardé, vous devriez voir toutes vos variables listées dans la section "Environment variables" avec leur valeur masquée (••••••) pour les variables sensibles.

### Étape 7: Configurer les paramètres d'exécution

1. Toujours dans l'onglet **"Configuration"**, sélectionnez **"General configuration"** dans le menu de gauche
2. Cliquez sur **"Edit"**
3. Configurez :
   - **Timeout**: Sélectionnez "5 min 0 sec" (300 secondes) - nécessaire pour traiter de grandes quantités de données
   - **Memory**: Définissez à 512 MB (ou plus selon vos besoins)
   - **Ephemeral storage**: Laissez la valeur par défaut (512 MB est généralement suffisant)
4. Cliquez sur **"Save"**

### Étape 8: Configurer un trigger EventBridge

Pour exécuter la fonction automatiquement :

1. Sur la page de la fonction Lambda, allez dans l'onglet **"Configuration"**
2. Dans le menu de gauche, sélectionnez **"Triggers"**
3. Cliquez sur **"Add trigger"**
4. Dans la liste des sources de trigger, sélectionnez **"EventBridge (CloudWatch Events)"**
5. Configurez le trigger :
   - **Rule**: Sélectionnez "Create a new rule"
   - **Rule name**: `pyvest-daily-export`
   - **Rule type**: Sélectionnez "Schedule expression"
   - **Schedule expression**: `cron(0 2 * * ? *)` (tous les jours à 2h du matin UTC)
6. Cliquez sur **"Add"** en bas de la page

### Étape 9: Tester la fonction

1. Sur la page de la fonction Lambda, allez dans l'onglet **"Test"** (en haut de la page)
2. Si c'est votre premier test, cliquez sur **"Create new test event"**
3. Configurez l'événement de test :
   - **Event name**: `test-event` (ou tout autre nom)
   - **Event JSON**: Utilisez simplement `{}` (objet vide)
4. Cliquez sur **"Save"**
5. Cliquez sur **"Test"** pour exécuter la fonction
6. Les résultats s'afficheront dans la section "Execution result"
7. Pour voir les logs détaillés, cliquez sur **"View logs in CloudWatch"** ou allez dans l'onglet **"Monitor"** > **"View CloudWatch logs"**

### Exécution manuelle

Vous pouvez également invoquer la fonction manuellement via :

**AWS CLI:**
```bash
aws lambda invoke --function-name pyvest-harvest-export --payload '{}' response.json
```

**AWS Console:**
- Allez dans la fonction Lambda > Onglet **"Test"**
- Sélectionnez l'événement de test existant ou créez-en un nouveau avec `{}`
- Cliquez sur **"Test"**

---

## 💻 Utilisation locale

Pour exécuter le script localement (hors Lambda) :

### Installation

1. Installer les dépendances :
```bash
pip install -r requirements.txt
```

2. Configurer le fichier `config.json` :
```json
{
    "account_id": "VOTRE_ACCOUNT_ID",
    "access_token": "VOTRE_ACCESS_TOKEN",
    "harvest_url": "https://api.harvestapp.com/v2/time_entries",
    "days_back": 90,
    "aws": {
        "access_key_id": "VOTRE_ACCESS_KEY_ID",
        "secret_access_key": "VOTRE_SECRET_ACCESS_KEY",
        "region": "us-east-1",
        "bucket_name": "votre-bucket-name"
    }
}
```

### Configuration AWS (pour usage local)

1. Créer un bucket S3 dans votre région AWS préférée
2. Créer un utilisateur IAM avec les permissions S3 suivantes :
   - `s3:PutObject`
   - `s3:GetObject`
3. Générer des clés d'accès pour cet utilisateur
4. Mettre à jour la configuration dans `config.json`

### Exécution

```bash
python pyvest.py
```

---

## 📁 Structure des fichiers S3

Les fichiers sont sauvegardés dans S3 avec les clés suivantes :
- `YYYYMMDD.json` : Données consolidées du jour (format: `20250101.json`)
- Les fichiers sont mis à jour automatiquement avec les nouvelles entrées et détection des suppressions

---

## 🔧 Mise à jour du code Lambda

Quand vous modifiez le code :

1. Modifiez le code localement
2. Reconstruisez le package ZIP :

**Option A : Utiliser le script (recommandé) :**
```bash
python create-lambda-package.py
```

**Option B : Manuellement :**
```bash
cd lambda-package
rm -rf * # Nettoyer (sauf .gitkeep si nécessaire)
pip install --no-user -r ../requirements.txt -t .
cp ../pyvest.py .
python -c "import shutil; shutil.make_archive('../pyvest-lambda', 'zip', '.')"
```

3. Dans AWS Console, allez dans Lambda > votre fonction `pyvest-harvest-export`
4. Allez dans l'onglet **"Code"**
5. Cliquez sur **"Upload from"** > **"Upload a .zip file"**
6. Sélectionnez le nouveau fichier `pyvest-lambda.zip`
7. Cliquez sur **"Save"**

**Ou utilisez AWS CLI :**
```bash
aws lambda update-function-code --function-name pyvest-harvest-export --zip-file fileb://pyvest-lambda.zip
```

---

## 📊 Monitoring

Les logs Lambda sont disponibles dans CloudWatch Logs :
- AWS Console > CloudWatch > Log groups > `/aws/lambda/pyvest-harvest-export`

Vous pouvez également configurer des alertes CloudWatch pour les erreurs Lambda.

---

## 🔐 Référence des variables d'environnement

Cette section fournit une référence complète de toutes les variables d'environnement supportées par PyVest Lambda.

### Variables requises

Ces variables doivent être configurées pour que la fonction Lambda fonctionne correctement :

#### `HARVEST_ACCOUNT_ID`
- **Type**: String (numérique)
- **Description**: Votre Harvest Account ID unique
- **Exemple**: `1339925`
- **Où trouver**: 
  - Harvest Dashboard > Settings (engrenage en haut à droite)
  - Personal API Access
  - Vous verrez votre Account ID en haut de la page

#### `HARVEST_ACCESS_TOKEN`
- **Type**: String (token Bearer)
- **Description**: Votre Personal Access Token Harvest pour l'authentification API
- **Exemple**: `2421489.pt.Uac1iLpnRXnegrIuw5KXryx4IvXu_GLvOaFDBH8ORMOPttzKQTh4XfR1QF8TSIubu3UmFefngYGrVy2vXnfhHQ`
- **Où créer**:
  1. Harvest Dashboard > Settings > Personal API Access
  2. Cliquez sur "Create a Personal Access Token"
  3. Donnez un nom (ex: "PyVest Lambda")
  4. Copiez le token généré (visible une seule fois)
- **Sécurité**: ⚠️ Token sensible - utilisez AWS Systems Manager Parameter Store chiffré si possible

#### `S3_BUCKET_NAME`
- **Type**: String
- **Description**: Nom de votre bucket S3 où les données seront stockées
- **Exemple**: `harvest-dump`
- **Format**: Doit suivre les conventions de nommage S3 (minuscules, tirets autorisés, pas de underscores)
- **Note**: Le bucket doit exister et le rôle Lambda doit avoir les permissions nécessaires

### Variables optionnelles

Ces variables ont des valeurs par défaut mais peuvent être personnalisées :

#### `HARVEST_URL`
- **Type**: String (URL)
- **Description**: URL de base de l'API Harvest
- **Valeur par défaut**: `https://api.harvestapp.com/v2/time_entries`
- **Quand modifier**: Seulement si vous utilisez un endpoint personnalisé ou une version différente de l'API
- **Exemple**: `https://api.harvestapp.com/v2/time_entries`

#### `DAYS_BACK`
- **Type**: Integer
- **Description**: Nombre de jours en arrière depuis aujourd'hui pour récupérer les time entries
- **Valeur par défaut**: `90`
- **Valeurs recommandées**: 
  - `21` - 3 semaines (pour des exports fréquents)
  - `30` - 1 mois
  - `90` - 3 mois (par défaut)
  - `365` - 1 an (attention à la performance)
- **Note**: Plus le nombre est élevé, plus l'exécution Lambda prendra de temps

#### `AWS_REGION`
- **Type**: String (code région AWS)
- **Description**: Région AWS où se trouve votre bucket S3
- **Valeur par défaut**: Déduit automatiquement depuis `AWS_LAMBDA_FUNCTION_NAME` ou `AWS_DEFAULT_REGION`
- **Exemples**: `us-east-1`, `us-west-2`, `eu-west-1`, `ap-southeast-1`
- **Quand définir**: Seulement si la région ne peut pas être déduite automatiquement
- **Note**: Cette variable est généralement gérée automatiquement par Lambda

### Configuration via AWS Systems Manager Parameter Store (recommandé pour production)

Pour une sécurité renforcée, surtout en production, utilisez AWS Systems Manager Parameter Store pour stocker les valeurs sensibles :

1. **Créer les paramètres dans Parameter Store**:
   - AWS Console > Systems Manager > Parameter Store
   - Créez des paramètres de type "SecureString" chiffrés avec KMS
   - Exemple: `/pyvest/harvest/account_id`, `/pyvest/harvest/access_token`

2. **Référencer dans Lambda Environment Variables**:
   ```
   HARVEST_ACCOUNT_ID = {{resolve:ssm:/pyvest/harvest/account_id:1}}
   HARVEST_ACCESS_TOKEN = {{resolve:ssm:/pyvest/harvest/access_token:1}}
   ```

3. **Ajouter les permissions IAM**:
   - Ajoutez à votre rôle Lambda: `ssm:GetParameter`, `ssm:GetParameters` 
   - Et pour KMS: `kms:Decrypt` (si vous utilisez un KMS key personnalisé)

**Exemple de policy IAM supplémentaire pour Parameter Store**:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ssm:GetParameter",
                "ssm:GetParameters"
            ],
            "Resource": "arn:aws:ssm:*:*:parameter/pyvest/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "kms:Decrypt"
            ],
            "Resource": "arn:aws:kms:*:*:key/*"
        }
    ]
}
```

### Vérification de la configuration

Pour vérifier que vos variables d'environnement sont correctement configurées, testez la fonction Lambda. Si des variables requises manquent, vous verrez une erreur dans les logs CloudWatch :

```
ValueError: Les variables d'environnement HARVEST_ACCOUNT_ID et HARVEST_ACCESS_TOKEN sont requises
```

ou

```
ValueError: La variable d'environnement S3_BUCKET_NAME est requise
```
