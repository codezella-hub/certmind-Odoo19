# Configuration du pipeline

## Secrets GitHub à créer

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Nom | Valeur |
|---|---|
| `ACR_USERNAME` | `certmindacr` |
| `ACR_PASSWORD` | voir la commande ci-dessous |

```bash
az acr credential show --name certmindacr --query "passwords[0].value" -o tsv
```

Ce sont les **seuls** secrets nécessaires. L'authentification Azure passe
par OIDC et ne stocke aucun mot de passe.

## Pourquoi pas de service principal

Le tenant ESPRIT interdit aux comptes étudiants d'en créer :

```
az ad sp create-for-rbac ...
→ Insufficient privileges to complete the operation
```

On utilise donc une **identité managée** avec **fédération OIDC**. GitHub
présente un jeton signé prouvant l'origine du workflow (dépôt + branche),
et Azure l'accepte sans mot de passe partagé.

Ressources créées pour cela :

```bash
# 1. L'identité (ne touche pas à l'annuaire, donc autorisée)
az identity create --name certmind-github --resource-group rg-certmind

# 2. Le droit de modifier les ressources du groupe
az role assignment create \
  --assignee 812d6b56-31ec-4050-87b0-2a4486a8c2e6 \
  --role Contributor \
  --scope /subscriptions/6073ec94-85a9-4fd3-8217-ed5f5d574928/resourceGroups/rg-certmind

# 3. La fédération : seul ce dépôt, sur cette branche, peut s'authentifier
az identity federated-credential create \
  --name github-main \
  --identity-name certmind-github \
  --resource-group rg-certmind \
  --issuer https://token.actions.githubusercontent.com \
  --subject repo:codezella-hub/certmind-Odoo19:ref:refs/heads/main \
  --audiences api://AzureADTokenExchange
```

Les identifiants inscrits dans le workflow (`AZURE_CLIENT_ID`,
`AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`) ne sont pas des secrets :
ils n'ouvrent rien sans un jeton émis par GitHub pour ce dépôt précis.

## Étendre à une autre branche

La fédération est liée à `refs/heads/main`. Pour autoriser une branche
supplémentaire, créez une seconde `federated-credential` avec un autre
`--subject`.

## Après un déploiement

Le pipeline publie la nouvelle image et redéploie le container. Mais si
le commit modifie un **modèle** Odoo — nouveau champ, nouvelle vue — la
base doit aussi être mise à jour :

```bash
az containerapp exec --name certmind-odoo --resource-group rg-certmind --command /bin/bash

# dans le container :
odoo --config=/etc/odoo/odoo.conf -d odoo -u nom_du_module --stop-after-init --no-http
```

Sans cette étape, le code est à jour mais la base ne connaît pas les
nouvelles colonnes, et Odoo lève une erreur du type
*« la colonne xxx n'existe pas »*.
